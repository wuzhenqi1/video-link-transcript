---
name: video-link-transcript
description: GPU-only transcript extraction for Douyin and Bilibili. Accepts video links, link files, creator pages, Bilibili UIDs, and Douyin handles, resolves public video URLs, and saves simplified-Chinese txt output under the configured output folder.
---

# Video Link Transcript

Use this skill when the user wants `.txt` transcripts from Douyin or Bilibili and the input may be either video-level or creator-level.

## Output

- only `.txt`
- one creator one folder
- output root is configurable with `--output-root`
- filename uses the extracted title when available
- saved text must be normalized to simplified Chinese

## Inputs

- one video link
- multiple video links
- TXT with one link per line
- CSV with a required `url` column and optional `title` column
- creator page URL
- Bilibili UID with `--platform bilibili`
- Douyin `sec_uid` or handle with `--platform douyin`

## Workflow

1. Accept one or more sources.
2. Resolve them into public video URLs. For creator inputs, prefer `scripts/collect_public_video_urls.py`.
3. Run `scripts/batch_extract_transcripts.py`.
4. Let it call the bundled `scripts/extract.py` for each video.
5. Save each transcript as `<output-root>/<creator-name>/<title>.txt`.

## Run

Basic:

```bash
python scripts/batch_extract_transcripts.py "<source>" --creator "<creator-name>"
```

Useful options:

- `--output-root`: override the output folder
- `--creator-url`: crawl a creator page directly
- `--creator-id`: crawl from a creator ID or UID
- `--platform`: required with `--creator-id`, either `douyin` or `bilibili`
- `--cookies-from-browser`: reuse local browser cookies for creator pages
- `--extractor`: override the bundled `scripts/extract.py`
- `--use-edge-profile`: reuse a signed-in local Edge profile for Douyin handle resolution
- `--edge-profile-dir`: Edge profile directory name such as `Default`
- `--count` or `--limit`: process only the first N links
- `--skip-existing`: skip files that already exist

Examples:

```bash
python scripts/batch_extract_transcripts.py "<douyin-video-url>" --creator "creator-a"
```

```bash
python scripts/batch_extract_transcripts.py "<douyin-video-url>" "<bilibili-video-url>" --creator "mixed-sample"
```

```bash
python scripts/batch_extract_transcripts.py "./links.txt" --creator "creator-b" --model small --device cuda --compute-type float16 --batch-size 8 --limit 5
```

```bash
python scripts/batch_extract_transcripts.py --creator-url "<creator-page-url>" --count 10
```

```bash
python scripts/batch_extract_transcripts.py --creator-id "MS4wLjABAAAA..." --platform douyin --count 10
```

```bash
python scripts/batch_extract_transcripts.py --creator-id "asdfg9273" --platform douyin --count 10
```

```bash
python scripts/collect_public_video_urls.py --creator-id "<douyin-handle>" --platform douyin --count 20 --use-edge-profile --edge-profile-dir Default
```

## GPU

- GPU only
- `--device cuda`
- `--compute-type float16`
- `--batch-size 8`
- if CUDA is unavailable, exit instead of falling back to CPU

## Limits

- Creator-page crawling depends on the platform exposing a public video list.
- For Douyin handles, `--use-edge-profile` is preferred when Edge is already signed in.
- If a creator page is protected or not enumerable, ask for direct video URLs.
- Do not promise access to private or non-public content.

## Dependencies

Install local script dependencies with:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

This skill includes a bundled local extractor:

- `scripts/extract.py`

Only override it when you intentionally want a different extractor.
