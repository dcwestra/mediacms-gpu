# Upstream sync: fix the merge

You are running unattended in GitHub Actions, in a fork of MediaCMS whose `gpu` branch adds
NVIDIA GPU encoding. The workflow merged a new upstream MediaCMS release into `gpu` and it
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
- `files/tasks.py` (chunk split) and `files/models/encoding.py` (chunk concat): `-threads FFMPEG_THREADS`.
- `cms/settings.py`: `FFMPEG_THREADS = 0` (0 lets ffmpeg decide).
- `Dockerfile`: the Jellyfin ffmpeg portable build (version + sha256 ARGs, downloaded in the
  `build-image` stage) replaces upstream's ffmpeg/ffprobe in the `base` stage.

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
