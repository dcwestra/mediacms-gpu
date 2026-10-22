import json
import os
import re

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from files import helpers

CUVID_INPUT_ARGS = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-c:v", "h264_cuvid"]


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


def command(info=None, resolution=720, codec="h264"):
    return helpers.produce_ffmpeg_commands("in.mp4", info or media_info(), resolution, codec, "out.mp4", "pass")[0]


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


class GpuEncoderTests(SimpleTestCase):
    def test_h264_profile_encodes_with_nvenc_constqp(self):
        cmd = command()

        self.assertEqual(output_encoder(cmd), "h264_nvenc")
        self.assertEqual(cmd[cmd.index("-rc") + 1], "constqp")
        self.assertEqual(cmd[cmd.index("-cq") + 1], str(helpers.VIDEO_CRFS["h264"]))
        self.assertEqual(cmd[cmd.index("-preset") + 1], "p4")
        self.assertNotIn("-crf", cmd)

    def test_h265_profile_encodes_with_hevc_nvenc(self):
        cmd = command(codec="h265")

        self.assertEqual(output_encoder(cmd), "hevc_nvenc")
        self.assertEqual(cmd[cmd.index("-cq") + 1], str(helpers.VIDEO_CRFS["h265"]))

    def test_codec_aliases_map_to_nvenc(self):
        self.assertEqual(output_encoder(command(codec="avc1")), "h264_nvenc")
        self.assertEqual(output_encoder(command(codec="hvc1")), "hevc_nvenc")

    def test_vp9_profile_stays_on_libvpx_without_hwaccel(self):
        cmd = helpers.produce_ffmpeg_commands("in.mp4", media_info(), 720, "vp9", "out.webm", "pass")[0]

        self.assertEqual(output_encoder(cmd), "libvpx-vp9")
        self.assertNotIn("-hwaccel", cmd)

    def test_profile_without_codec_is_rejected(self):
        self.assertFalse(helpers.produce_ffmpeg_commands("in.mp4", media_info(), 720, None, "out.mp4", "pass"))


class GpuDecoderTests(SimpleTestCase):
    def test_h264_input_is_decoded_with_cuvid(self):
        cmd = command(media_info(video_codec="h264"))

        self.assertEqual(input_args(cmd), CUVID_INPUT_ARGS)
        self.assertTrue(video_filters(cmd).startswith("hwdownload,format=nv12,scale="))

    def test_h264_input_is_downloaded_before_deinterlacing(self):
        cmd = command(media_info(video_codec="h264", interlaced=True))

        self.assertTrue(video_filters(cmd).startswith("hwdownload,format=nv12,yadif,"))

    def test_h264_input_uses_cuvid_for_h265_profiles_too(self):
        self.assertEqual(input_args(command(media_info(video_codec="h264"), codec="h265")), CUVID_INPUT_ARGS)

    def test_other_inputs_use_generic_cuda_hwaccel(self):
        for codec in ("hevc", "vp9", "av1", "prores", None):
            with self.subTest(input_codec=codec):
                cmd = command(media_info(video_codec=codec))

                self.assertEqual(input_args(cmd), ["-hwaccel", "cuda"])
                self.assertNotIn("h264_cuvid", cmd)
                self.assertNotIn("hwdownload", video_filters(cmd))

    def test_scale_filter_is_aspect_aware(self):
        filters = video_filters(command(resolution=720))

        self.assertIn("scale=w='if(gt(a,16/9),1280,-2)':h='if(gt(a,16/9),-2,720)'", filters)


class GpuThreadsTests(SimpleTestCase):
    def test_threads_setting_leads_the_encode_command(self):
        self.assertEqual(command()[1:3], ["-threads", str(settings.FFMPEG_THREADS)])

    @override_settings(FFMPEG_THREADS=4)
    def test_threads_setting_is_read_at_call_time(self):
        self.assertEqual(command()[1:3], ["-threads", "4"])

    def test_chunk_split_command_passes_threads(self):
        source = read_source("files", "tasks.py")

        self.assertRegex(
            source,
            re.compile(r'settings\.FFMPEG_COMMAND,\s*"-threads",\s*str\(settings\.FFMPEG_THREADS\),\s*"-y",\s*"-i",\s*media\.media_file\.path,\s*"-c",\s*"copy",\s*"-f",\s*"segment"'),
        )

    def test_chunk_concat_command_passes_threads(self):
        source = read_source("files", "models", "encoding.py")

        self.assertRegex(
            source,
            re.compile(r'settings\.FFMPEG_COMMAND,\s*"-threads",\s*str\(settings\.FFMPEG_THREADS\),\s*"-y",\s*"-f",\s*"concat"'),
        )
