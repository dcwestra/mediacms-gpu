import json
import os
import re

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from files import helpers

VAAPI_DEFAULT_INPUT_ARGS = [
    "-init_hw_device",
    "vaapi=va:/dev/dri/renderD128",
    "-filter_hw_device",
    "va",
    "-hwaccel",
    "vaapi",
    "-hwaccel_device",
    "va",
]


def media_info(**overrides):
    info = {
        "video_frame_rate_n": 30,
        "video_frame_rate_d": 1,
        "video_height": 1080,
        "video_duration": 600,
        "has_audio": True,
        "interlaced": False,
        "video_codec": "h264",
    }
    info.update(overrides)
    return json.dumps(info)


def commands(info=None, resolution=720, codec="h264"):
    return helpers.produce_ffmpeg_commands("in.mp4", info or media_info(), resolution, codec, "out.mp4", "pass")


def command(*args, **kwargs):
    return commands(*args, **kwargs)[0]


def input_args(cmd):
    """Everything between the -threads/-y prefix and -i."""
    return cmd[cmd.index("-y") + 1 : cmd.index("-i")]


def output_encoder(cmd):
    return cmd[cmd.index("-c:v", cmd.index("-i")) + 1]


def video_filters(cmd):
    return cmd[cmd.index("-filter:v") + 1]


def read_source(*parts):
    with open(os.path.join(settings.BASE_DIR, *parts)) as f:
        return f.read()


def compose_service(path, name):
    """The indented body of one service in a compose file."""
    match = re.search(rf"^  {name}:\n((?:    .*\n|[ \t]*\n)*)", read_source(path), re.M)
    return match.group(1) if match else ""


@override_settings(FFMPEG_GPU="intel")
class IntelEncoderTests(SimpleTestCase):
    def test_h264_profile_encodes_with_vaapi_constant_qp(self):
        cmd = command()

        self.assertEqual(output_encoder(cmd), "h264_vaapi")
        self.assertEqual(cmd[cmd.index("-rc_mode") + 1], "CQP")
        self.assertEqual(cmd[cmd.index("-qp") + 1], str(helpers.VIDEO_CRFS["h264"]))
        self.assertEqual(cmd[cmd.index("-profile:v") + 1], "main")
        self.assertNotIn("-crf", cmd)

    def test_h265_profile_encodes_with_hevc_vaapi(self):
        cmd = command(codec="h265")

        self.assertEqual(output_encoder(cmd), "hevc_vaapi")
        self.assertEqual(cmd[cmd.index("-qp") + 1], str(helpers.VIDEO_CRFS["h265"]))
        self.assertNotIn("-level", cmd)

    def test_codec_aliases_map_to_vaapi(self):
        self.assertEqual(output_encoder(command(codec="avc1")), "h264_vaapi")
        self.assertEqual(output_encoder(command(codec="hvc1")), "hevc_vaapi")

    def test_no_nvidia_options(self):
        cmd = command()

        for option in ("-rc", "-cq", "-preset", "-cuda", "-hwaccel_output_format"):
            self.assertNotIn(option, cmd)
        self.assertNotIn("cuda", cmd)

    def test_pix_fmt_is_left_to_the_filter_graph(self):
        # -pix_fmt would be applied after hwupload and break the GPU surface chain
        self.assertNotIn("-pix_fmt", command())

    def test_h264_level_follows_the_resolution(self):
        hd = command(media_info(), resolution=1080)
        uhd = command(media_info(video_height=2160), resolution=2160)

        self.assertEqual(hd[hd.index("-level") + 1], "42")
        self.assertEqual(uhd[uhd.index("-level") + 1], "52")

    def test_keyframes_are_forced_for_hls_segmenting(self):
        cmd = command()

        self.assertEqual(cmd[cmd.index("-force_key_frames") + 1], "expr:gte(t,n_forced*4)")
        self.assertEqual(cmd[cmd.index("-g") + 1], str(int(30 * helpers.KEYFRAME_DISTANCE * 2)))

    def test_vp9_profile_stays_on_libvpx_without_hwaccel(self):
        cmd = command(codec="vp9")

        self.assertEqual(output_encoder(cmd), "libvpx-vp9")
        self.assertNotIn("-hwaccel", cmd)
        self.assertNotIn("-init_hw_device", cmd)

    def test_profile_without_codec_is_rejected(self):
        self.assertFalse(commands(codec=None))


@override_settings(FFMPEG_GPU="intel")
class IntelDecoderTests(SimpleTestCase):
    def test_every_input_uses_vaapi_hwaccel_with_software_fallback(self):
        # no -hwaccel_output_format: frames return to system memory, and ffmpeg
        # decodes in software any stream the GPU can't, whatever the input codec
        for codec in ("h264", "hevc", "vp9", "av1", "prores", None):
            with self.subTest(input_codec=codec):
                cmd = command(media_info(video_codec=codec))

                self.assertEqual(input_args(cmd), VAAPI_DEFAULT_INPUT_ARGS)
                self.assertNotIn("-hwaccel_output_format", cmd)

    def test_filters_run_on_the_cpu_then_upload_to_the_gpu(self):
        filters = video_filters(command())

        self.assertTrue(filters.startswith("scale="))
        self.assertTrue(filters.endswith(",format=nv12,hwupload"))
        self.assertNotIn("hwdownload", filters)

    def test_interlaced_input_is_deinterlaced_first(self):
        self.assertTrue(video_filters(command(media_info(interlaced=True))).startswith("yadif,scale="))

    def test_scale_filter_is_aspect_aware(self):
        filters = video_filters(command(resolution=720))

        self.assertIn("scale=w='if(gt(a,16/9),1280,-2)':h='if(gt(a,16/9),-2,720)'", filters)

    @override_settings(FFMPEG_VAAPI_DEVICE="/dev/dri/renderD129")
    def test_render_node_is_configurable(self):
        self.assertEqual(input_args(command())[:2], ["-init_hw_device", "vaapi=va:/dev/dri/renderD129"])

    def test_render_node_defaults_when_the_setting_is_absent(self):
        with override_settings():
            del settings.FFMPEG_VAAPI_DEVICE
            self.assertEqual(input_args(command()), VAAPI_DEFAULT_INPUT_ARGS)


@override_settings(FFMPEG_GPU="intel")
class IntelRateControlTests(SimpleTestCase):
    def test_short_clips_are_single_pass_vbr(self):
        # VAAPI has no two-pass mode, so one command, not the pass 1 + pass 2 pair
        cmds = commands(media_info(video_duration=1))
        cmd = cmds[0]

        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmd[cmd.index("-rc_mode") + 1], "VBR")
        self.assertEqual(cmd[cmd.index("-b:v") + 1], "2500k")
        self.assertEqual(cmd[cmd.index("-maxrate") + 1], "3750k")
        self.assertEqual(cmd[cmd.index("-bufsize") + 1], "3750k")
        self.assertNotIn("-qp", cmd)
        self.assertNotIn("/dev/null", cmd)
        self.assertEqual(cmd[-1], "out.mp4")

    def test_long_videos_are_constant_qp(self):
        cmd = command(media_info(video_duration=600))

        self.assertEqual(cmd[cmd.index("-rc_mode") + 1], "CQP")
        self.assertNotIn("-b:v", cmd)
        self.assertNotIn("-maxrate", cmd)

    def test_low_power_is_left_to_the_driver_by_default(self):
        self.assertNotIn("-low_power", command())

    @override_settings(FFMPEG_VAAPI_LOW_POWER=True)
    def test_low_power_can_be_enabled(self):
        cmd = command()

        self.assertEqual(cmd[cmd.index("-low_power") + 1], "1")

    @override_settings(FFMPEG_VAAPI_LOW_POWER=False)
    def test_low_power_can_be_disabled_explicitly(self):
        cmd = command()

        self.assertEqual(cmd[cmd.index("-low_power") + 1], "0")


class GpuSelectionTests(SimpleTestCase):
    def test_nvidia_is_the_default_when_the_setting_is_absent(self):
        with override_settings():
            del settings.FFMPEG_GPU
            cmd = command()

        self.assertEqual(output_encoder(cmd), "h264_nvenc")
        self.assertEqual(input_args(cmd)[:2], ["-hwaccel", "cuda"])

    @override_settings(FFMPEG_GPU="nvidia")
    def test_nvidia_selects_nvenc(self):
        self.assertEqual(output_encoder(command()), "h264_nvenc")
        self.assertEqual(output_encoder(command(codec="h265")), "hevc_nvenc")

    @override_settings(FFMPEG_GPU="none")
    def test_none_uses_the_software_encoders(self):
        for codec, encoder in (("h264", "libx264"), ("h265", "libx265"), ("vp9", "libvpx-vp9")):
            with self.subTest(codec=codec):
                cmd = command(codec=codec)

                self.assertEqual(output_encoder(cmd), encoder)
                self.assertNotIn("-hwaccel", cmd)
                self.assertNotIn("-init_hw_device", cmd)
                self.assertIn("-pix_fmt", cmd)
                self.assertIn("-crf", cmd)

    @override_settings(FFMPEG_GPU=" Intel ")
    def test_the_setting_ignores_case_and_whitespace(self):
        self.assertEqual(output_encoder(command()), "h264_vaapi")

    @override_settings(FFMPEG_GPU="amd")
    def test_unknown_gpu_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "FFMPEG_GPU"):
            command()


class IntelDeploymentTests(SimpleTestCase):
    def test_intel_compose_override_moves_the_worker_to_the_render_node(self):
        worker = compose_service("docker-compose.intel.yaml", "celery_worker")

        self.assertIn("    runtime: runc\n", worker)
        self.assertIn("- /dev/dri:/dev/dri", worker)
        self.assertIn("FFMPEG_GPU: intel", worker)

    def test_intel_compose_override_leaves_the_image_to_the_base_file(self):
        self.assertNotIn("image:", compose_service("docker-compose.intel.yaml", "celery_worker"))

    def test_base_compose_files_still_default_to_nvidia(self):
        for path in ("docker-compose.yaml", "docker-compose/docker-compose-http-proxy.yaml"):
            with self.subTest(path=path):
                worker = compose_service(path, "celery_worker")

                self.assertIn("    runtime: nvidia\n", worker)
                self.assertNotIn("FFMPEG_GPU", worker)

    def test_entrypoint_gives_www_data_access_to_the_render_node(self):
        # celery runs as www-data under supervisord, which drops docker's group_add
        source = read_source("deploy", "docker", "entrypoint.sh")

        self.assertIn("/dev/dri/renderD*", source)
        self.assertIn('usermod -a -G "$NODE_GROUP" www-data', source)

    def test_image_installs_the_libva_userspace(self):
        # Jellyfin's portable ffmpeg dlopen()s libva and the VA driver rather than bundling them
        source = read_source("Dockerfile")

        for package in ("libva2", "libva-drm2", "intel-media-va-driver-non-free"):
            with self.subTest(package=package):
                self.assertIn(package, source)
