# Upstream sync: fix the merge

You are running unattended in GitHub Actions, in a fork of MediaCMS whose `gpu` branch adds
GPU encoding: NVIDIA NVENC by default, Intel VAAPI selectable. The workflow merged a new upstream MediaCMS release into `gpu` and it
went wrong: either `git merge` stopped with conflicts, or the merged code failed verification
(the Docker image build, the ffmpeg capability check, `manage.py check`, or the GPU tests in
`tests/gpu/`). "This run" above says which, and where the log is.

Your job: leave the working tree as a correct merge, one that keeps everything upstream changed
*and* every GPU customization. A human reviews your result as a pull request before it ships.

## The GPU customizations

They are listed in `.github/README.md` ("How it differs from MediaCMS") and pinned down by
`tests/gpu/test_gpu_encoding.py`. Read both first. In short:

- `files/helpers.py`: NVENC encoders for h264/h265, CUVID/CUDA decoding chosen by the *input*
  codec, NVENC rate control flags, an aspect-aware scale filter, and `-threads FFMPEG_THREADS`.
  The GPU is chosen by `settings.FFMPEG_GPU` (`GPU_ENCODERS`, `get_ffmpeg_gpu()`, `is_vaapi_encoder()`):
  `nvidia` (the default, as above), `intel` (VAAPI: `-hwaccel vaapi` decoding with software fallback,
  the CPU filters, `format=nv12,hwupload`, single-pass VBR at the per-resolution target bitrate with the same maxrate/bufsize cap as libx264, no `-pix_fmt`) or
  `none` (libx264/libx265). The NVIDIA output must stay exactly as it is.
- `files/tasks.py` (chunk split) and `files/models/encoding.py` (chunk concat): `-threads FFMPEG_THREADS`.
- `cms/settings.py`: `FFMPEG_THREADS = 0` (0 lets ffmpeg decide), and the environment-driven `FFMPEG_GPU`
  (default `nvidia`), `FFMPEG_VAAPI_DEVICE` and `FFMPEG_VAAPI_LOW_POWER`.
- `Dockerfile`: the Jellyfin ffmpeg portable build (version + sha256 ARGs, downloaded in the
  `build-image` stage) replaces upstream's ffmpeg/ffprobe in the `base` stage. The `base` stage also
  has a `RUN` that enables Debian's `non-free` component and installs `libva2`, `libva-drm2`,
  `intel-media-va-driver-non-free` and `vainfo`: that ffmpeg build loads libva at runtime.
- `deploy/docker/entrypoint.sh`: the `/dev/dri/renderD*` loop that adds `www-data` to the group owning
  the render node. Celery runs as `www-data` under supervisord, which drops docker's `group_add`.
- Compose files (`docker-compose.yaml`, `docker-compose.full.yaml`, `docker-compose-dev.yaml`,
  `docker-compose/*.yaml`): services use `ghcr.io/dcwestra/mediacms-gpu:latest` (`:full` in
  `docker-compose.full.yaml`) instead of `mediacms/mediacms`; the dev files keep their local build
  images. Every `celery_worker` has `runtime: nvidia` and `NVIDIA_VISIBLE_DEVICES: all` /
  `NVIDIA_DRIVER_CAPABILITIES: all`. Any compose file upstream adds needs the same treatment.
  `docker-compose.intel.yaml` is an override that works with any of them (`runtime: runc`, `/dev/dri`,
  `FFMPEG_GPU: intel` on `celery_worker`); the compose files themselves keep `runtime: nvidia`.

Everything else, including the celery/supervisord worker configuration, is upstream's.

## How to work

1. See what upstream changed: `git log --oneline <previous>..<release>` and
   `git diff <previous>..<release> -- <path>` for the files involved.
2. Conflicts: resolve every conflicted file listed above. Take upstream's version of everything,
   then re-apply the GPU customization on top of it in a way that fits upstream's new code.
   Remove every conflict marker. Don't stage anything.
3. Verification failure: read the log, find the cause, and make the smallest change that fixes it.
   If upstream restructured code a GPU customization depends on (for example renamed a setting or
   reorganised the ffmpeg command builder), move the customization to the new structure. Only
   change `tests/gpu/` when upstream made the asserted behaviour impossible, and explain why in
   the summary.
4. Run `python3 -m py_compile <file>` on every Python file you edited.

## Rules

- Minimal changes: no refactors, reformatting, new features, or edits unrelated to this merge.
- Never edit anything under `.github/`.
- Never stage, commit, push, or create branches. The workflow does that after you finish.
- Never add credentials, hostnames, or site-specific configuration.
- If you can't resolve something with confidence, stay as close to upstream as you can and say
  so plainly in the summary.

## Summary (required)

Write a Markdown summary to the summary path given above. It becomes the pull request
description. Include:

- What upstream changed that touches the GPU customizations.
- For each conflicted file, how you resolved it.
- For a verification failure, the cause and the fix.
- Anything uncertain or risky the reviewer should check.
