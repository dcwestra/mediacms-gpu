# MediaCMS GPU

[MediaCMS](https://github.com/mediacms-io/mediacms) with video encoding on NVIDIA GPUs.

This fork changes only how videos are encoded. Features, installation and configuration are the
same as upstream MediaCMS, so for everything else read the **[original MediaCMS README](/README.md)**.

## How it differs from MediaCMS

- **NVENC encoding.** h264 and h265 profiles encode with `h264_nvenc` / `hevc_nvenc` instead of
  libx264 / libx265. VP9 profiles stay on libvpx.
- **GPU decoding.** h264 sources are decoded on the GPU with `h264_cuvid`. Other sources use
  `-hwaccel cuda`, which is NVDEC where the GPU supports the format and software decoding otherwise.
- **Jellyfin ffmpeg.** The image ships the [Jellyfin ffmpeg](https://github.com/jellyfin/jellyfin-ffmpeg)
  portable build, which has NVENC/CUVID support, in place of the stock ffmpeg.
- **`FFMPEG_THREADS` setting.** Passed as `-threads` to the encode, chunk split and concat commands.
  The default `0` lets ffmpeg decide, as upstream does.
- **Compose files.** The repository's compose files run this fork's image, and `celery_worker`
  runs on the NVIDIA runtime.

Everything else is upstream MediaCMS, kept up to date automatically (see [Staying current](#staying-current)).

## Image

| Registry | Image |
|---|---|
| GitHub Container Registry | `ghcr.io/dcwestra/mediacms-gpu` |
| Docker Hub | `dcwestra/mediacms-gpu` |

| Tag | Contents |
|---|---|
| `latest`, `<version>` (e.g. `9.3.1`), `sha-<commit>` | MediaCMS with GPU encoding |
| `full`, `<version>-full`, `sha-<commit>-full` | The same plus [Whisper](https://github.com/openai/whisper) transcription, which also runs on the GPU (Turing or newer, see below) |

## Running it

The host needs the NVIDIA driver and the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html),
with the `nvidia` runtime registered in Docker (`sudo nvidia-ctk runtime configure --runtime=docker`,
then restart Docker).

Then follow upstream's [Docker installation docs](/docs/admins_docs.md). The compose files in this
repository already use the GPU image:

```sh
git clone https://github.com/dcwestra/mediacms-gpu.git
cd mediacms-gpu
docker compose up -d
```

For Whisper transcription, add the full image and set `USE_WHISPER_TRANSCRIBE = True` in your settings:

```sh
docker compose -f docker-compose.yaml -f docker-compose.full.yaml up -d
```

The full image's PyTorch (CUDA 13) supports NVIDIA GPUs from Turing on (compute capability 7.5+:
GTX 16xx, RTX 20xx and newer, Quadro T-series and newer). On older GPUs, such as Pascal (GTX 10xx,
Quadro P-series), Whisper tries to use the GPU and fails, so use the standard image there. Video
encoding isn't affected: it uses ffmpeg, which supports these older GPUs.

With your own compose file, use this image and put `celery_worker`, which runs the encodes, on the NVIDIA runtime:

```yaml
  celery_worker:
    image: ghcr.io/dcwestra/mediacms-gpu:latest
    runtime: nvidia
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: all
```

If you don't mount the whole project directory into the containers (the upstream compose files do),
set the same `SECRET_KEY` environment variable on every MediaCMS container. Otherwise each container
generates its own key at startup.

### Small servers

Encodes still use the CPU for scaling and audio, and by default celery runs one encode per CPU core.
To keep the rest of the server responsive, you can:

- Bind-mount your own `deploy/docker/supervisord/supervisord-celery_long.conf` with `-c 2` added
  to the celery command, to cap concurrent encodes.
- Set `FFMPEG_THREADS = 1` in `local_settings.py` to limit decoding threads.

## Staying current

[upstream-sync.yml](/.github/workflows/upstream-sync.yml) checks daily for a new MediaCMS release
and merges it into the `gpu` branch:

- **Clean merge.** The image is built and verified ([verify.sh](/.github/upstream-sync/verify.sh):
  ffmpeg NVENC/CUVID support, `manage.py check`, [GPU tests](/tests/gpu/test_gpu_encoding.py)).
  If it passes, the merge goes to `gpu` and [gpu-image.yml](/.github/workflows/gpu-image.yml)
  publishes the image.
- **Conflict or failed verification.** Claude Code fixes the merge following
  [claude-prompt.md](/.github/upstream-sync/claude-prompt.md), verification runs again, and the
  result is opened as a pull request for review.
- **Still failing.** An issue is opened with the logs.

## Maintaining the fork

- `main` mirrors upstream. `gpu` (the default branch) is upstream plus the changes above.

## License

AGPL-3.0, the same as [MediaCMS](/LICENSE.txt).
