# Video Link Transcript

[简体中文 README](./README.zh-CN.md)

GPU-only transcript extraction for Douyin and Bilibili.

Accepts video links, link files, creator pages, Bilibili UIDs, and Douyin handles. Resolves public video URLs and saves simplified-Chinese transcript output as plain `.txt` files under the configured output folder.

## What It Supports

- one Bilibili or Douyin video link
- multiple video links
- TXT files with one link per line
- CSV files with a required `url` column and optional `title` column
- Bilibili creator page URLs
- Bilibili UID
- Douyin creator page URLs
- Douyin `sec_uid`
- Douyin handle / 抖音号 / search token
- a Douyin video URL when you want to trace back to the creator page first

## Output Rules

- output is `.txt` only
- one creator goes into one folder
- output root is configurable with `--output-root`
- transcript text is normalized to simplified Chinese before saving
- no CSV summaries
- no JSONL indexes
- no extra report folders

## Setup

Install the Python dependencies used by the local scripts:

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

The extractor is now bundled in this repo at `scripts/extract.py`.

If you want to point to another extractor implementation, pass `--extractor` explicitly.

## GPU Requirement

This project is intentionally GPU-only. If CUDA is unavailable, the batch script exits immediately and does not fall back to CPU.

Use:

```powershell
--device cuda --compute-type float16 --batch-size 8
```

Make sure the Python environment includes CUDA-capable `faster-whisper` and `ctranslate2`.

## Usage

```powershell
python scripts/batch_extract_transcripts.py "<douyin-video-url>" --creator "creator-a" --device cuda --compute-type float16 --batch-size 8
```

```powershell
python scripts/batch_extract_transcripts.py "<douyin-video-url>" "<bilibili-video-url>" --creator "mixed-sample" --device cuda --compute-type float16 --batch-size 8
```

```powershell
python scripts/batch_extract_transcripts.py ".\\links.txt" --creator "creator-b" --device cuda --compute-type float16 --batch-size 8 --limit 5
```

```powershell
python scripts/batch_extract_transcripts.py --creator-id "<bilibili-uid>" --platform bilibili --count 2 --device cuda --compute-type float16 --batch-size 8
```

```powershell
python scripts/batch_extract_transcripts.py --creator-id "<douyin-handle>" --platform douyin --count 2 --use-edge-profile --edge-profile-dir Default --show-browser --device cuda --compute-type float16 --batch-size 8
```

Collect links only:

```powershell
python scripts/collect_public_video_urls.py --creator-id "<douyin-handle>" --platform douyin --count 20 --use-edge-profile --edge-profile-dir Default --show-browser
```

## Notes

- Douyin handle resolution works best with a signed-in Edge profile.
- `--use-edge-profile` is preferred when Edge is already logged in.
- Some creator pages may still fail to enumerate depending on public page structure.
- Direct video URLs are the most reliable input form.

## Limits

- This skill only works with public or publicly enumerable video pages.
- It does not promise access to private, protected, or non-public creator pages.
- Douyin and Bilibili can change page structure or apply rate limits.
