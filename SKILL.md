---
name: video-text-extractor
description: Extract text from Bilibili and Douyin video links by using subtitles first and Whisper fallback. Use when the user wants to turn a B站 or 抖音 video URL or share text into transcript text, or needs the bundled extractor script used.
---

# Video Text Extractor

## Overview

Use this skill to turn B站 or 抖音 links into transcript text.

## Workflow

1. Accept a Bilibili or Douyin share text or URL.
2. Extract the first supported link if the input is plain share text.
3. Prefer platform subtitles.
4. Fall back to downloaded audio plus Whisper ASR.
5. Return plain text by default, or JSON when requested.

## Usage

Run the bundled script in `scripts/extract.py`.

Common options:

- `--json`: emit structured JSON
- `--model`: choose Whisper size (`tiny`, `base`, `small`, `medium`, `large-v3`)
- `--proxy`: set HTTP proxy for network access
- `--device`: choose `cuda`, `cpu`, or `auto`
- `--compute-type`: choose `float16`, `int8`, or `int8_float16`
- `--batch-size`: raise on GPU for higher throughput
- `--hf-endpoint`: set a Hugging Face mirror such as `https://hf-mirror.com`

Example:

```bash
python scripts/extract.py "https://www.bilibili.com/video/..."
python scripts/extract.py --json --model turbo --device cuda --compute-type float16 --batch-size 8 --hf-endpoint https://hf-mirror.com "https://v.douyin.com/xxxxx/"
```

## Notes

- Support only Bilibili and Douyin.
- Prefer subtitles when available for speed and accuracy.
- Use browser cookies for Douyin if download access needs them.
- Install Python dependencies from `scripts/requirements.txt`.
- On GPU machines, prefer `turbo` or `distil-large-v3` with `--device cuda`.
- On Windows, CUDA 12 and cuDNN 9 libraries must be installed for GPU execution.
- On Windows, this skill can also use `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-runtime-cu12`, and `nvidia-cuda-nvrtc-cu12` from pip if the full CUDA toolkit is not installed.
- If direct Hugging Face access is slow or blocked, pass `--hf-endpoint https://hf-mirror.com`.
- Ensure `ffmpeg` is available on the system path.
