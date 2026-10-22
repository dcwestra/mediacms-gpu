#!/usr/bin/env bash
# Verifies a built GPU image: Jellyfin ffmpeg with NVENC/CUVID, Django boots, GPU tests pass.
#
# usage: verify.sh <image>
# Set DOCKER=podman to run it locally with podman.
set -euo pipefail

image="${1:?usage: verify.sh <image>}"
docker="${DOCKER:-docker}"
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"

in_image() {
    "$docker" run --rm -e SECRET_KEY=verify-only --entrypoint sh "$@"
}

echo "== ffmpeg"
ffmpeg_info="$(in_image "$image" -c 'ffmpeg -hide_banner -version | head -1; ffmpeg -hide_banner -encoders 2>/dev/null; ffmpeg -hide_banner -decoders 2>/dev/null')"
head -1 <<<"$ffmpeg_info"
for want in "Jellyfin" " h264_nvenc " " hevc_nvenc " " h264_cuvid "; do
    if ! grep -q -- "$want" <<<"$ffmpeg_info"; then
        echo "FAIL: ffmpeg in the image is missing '${want# }'" >&2
        exit 1
    fi
done
echo "ok: Jellyfin build with h264_nvenc, hevc_nvenc, h264_cuvid"

echo "== django check"
in_image "$image" -c 'python manage.py check'

echo "== GPU tests"
# tests/ is excluded from the image, so mount the GPU tests in. --noconftest skips the
# root conftest (it clears the Redis cache); cms.settings because test_settings copies
# media_files that the image doesn't ship.
in_image -v "$repo_root/tests/gpu:/home/mediacms.io/mediacms/tests/gpu:ro,z" "$image" -c \
    'uv pip install --quiet pytest pytest-django && pytest --noconftest --ds=cms.settings -p no:cacheprovider -q tests/gpu'

echo "== all checks passed"
