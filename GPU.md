# MediaCMS GPU

A fork of [MediaCMS](https://github.com/mediacms-io/mediacms) that encodes video on NVIDIA GPUs.
The `gpu` branch carries a small set of changes on top of upstream releases; `main` tracks upstream.

## What's different

- h264 and h265 encoding profiles use NVENC (`h264_nvenc` / `hevc_nvenc`). VP9 stays on libvpx.
- h264 sources are decoded on the GPU with `h264_cuvid`. Other sources use `-hwaccel cuda`:
  NVDEC where the GPU supports the format, software decoding otherwise.
- The image ships the [Jellyfin ffmpeg](https://github.com/jellyfin/jellyfin-ffmpeg) portable build
  in place of the stock ffmpeg.
- `FFMPEG_THREADS` setting (default `1`) for the encode, chunk split and concat commands.
- The `long_tasks` celery worker runs 2 concurrent tasks, to bound concurrent NVENC sessions.

## Image

`ghcr.io/dcwestra/mediacms-gpu`, built by [.github/workflows/gpu-image.yml](.github/workflows/gpu-image.yml)
on every push to `gpu`. Tags: `latest`, the MediaCMS version (e.g. `9.3.1`) and `sha-<commit>`.

## Running

Use the upstream docker compose setup with this image, plus the NVIDIA container runtime on
the services that encode (at least `celery_worker`):

```yaml
  celery_worker:
    image: ghcr.io/dcwestra/mediacms-gpu:latest
    runtime: nvidia
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: all
```

Requires the NVIDIA driver and the NVIDIA Container Toolkit on the host.

If you don't mount the whole project directory into the containers (the upstream compose files do),
set the same `SECRET_KEY` environment variable on every MediaCMS container. Otherwise each container
generates its own key at startup.

## Updating from upstream

```sh
git fetch upstream --tags
git switch gpu
git merge vX.Y.Z      # the upstream release tag
git push origin gpu   # CI builds and publishes the new image
```
