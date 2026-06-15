#!/usr/bin/env python3
"""Batch transcript extraction from URLs, creator pages, or creator IDs."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from collect_public_video_urls import (
    collect_urls,
    resolve_creator_input,
)


def sanitize_filename(name: str, max_len: int = 120) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if not name:
        return "untitled"
    return name[:max_len].rstrip()


def to_simplified_chinese(text: str) -> str:
    text = text or ""
    if not text:
        return text

    try:
        from opencc import OpenCC  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "缺少简繁转换依赖 opencc。\n"
            "请先安装：pip install opencc-python-reimplemented"
        ) from exc

    converter = OpenCC("t2s")
    return converter.convert(text)


def is_http_url(token: str) -> bool:
    return token.startswith(("http://", "https://"))


def is_direct_video_url(token: str) -> bool:
    token = token.strip()
    patterns = [
        r"https?://v\.douyin\.com/[a-zA-Z0-9_-]+/?",
        r"https?://www\.douyin\.com/video/\d+",
        r"https?://www\.iesdouyin\.com/video/\d+",
        r"https?://www\.douyin\.com/share/video/\d+",
        r"https?://www\.bilibili\.com/video/BV[a-zA-Z0-9]{10}[^\s]*",
        r"https?://b23\.tv/[a-zA-Z0-9]+[^\s]*",
    ]
    return any(re.search(pattern, token) for pattern in patterns)


def read_items(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if "url" not in (reader.fieldnames or []):
                raise SystemExit("CSV must include a 'url' column.")
            rows: list[dict[str, str]] = []
            for row in reader:
                url = (row.get("url") or "").strip()
                if not url:
                    continue
                rows.append(
                    {
                        "url": url,
                        "title": (row.get("title") or "").strip(),
                    }
                )
            return dedupe_items(rows)

    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append({"url": line, "title": ""})
    return dedupe_items(rows)


def dedupe_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in items:
        url = item["url"]
        if url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def fallback_stem(index: int, url: str) -> str:
    video_id = url.rstrip("/").split("/")[-1].split("?")[0]
    return f"{index:04d}-{sanitize_filename(video_id, max_len=80)}"


def choose_stem(index: int, url: str, extracted_title: str, input_title: str) -> str:
    title = extracted_title.strip() or input_title.strip()
    if title:
        return sanitize_filename(title)
    return fallback_stem(index, url)


def resolve_creator_urls(
    page_url: str,
    count: int,
    proxy: str,
    browser_cookies: str,
    browser_wait: int,
    show_browser: bool,
    use_edge_profile: bool,
    edge_profile_dir: str,
) -> tuple[list[str], str]:
    resolved_url, platform = resolve_creator_input(
        creator_url=page_url,
        creator_id="",
        platform="",
        proxy=proxy,
        browser_cookies=browser_cookies,
    )
    return collect_urls(
        page_url=resolved_url,
        platform=platform,
        count=count,
        proxy=proxy,
        browser_cookies=browser_cookies,
        browser_wait=browser_wait,
        headless=not show_browser,
        use_edge_profile=use_edge_profile,
        edge_profile_dir=edge_profile_dir,
    )


def dedupe_urls(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


def expand_source_token(
    token: str,
    *,
    platform: str,
    count: int,
    proxy: str,
    hf_endpoint: str,
    browser_cookies: str,
    browser_wait: int,
    show_browser: bool,
    use_edge_profile: bool,
    edge_profile_dir: str,
) -> tuple[list[dict[str, str]], str]:
    token = token.strip()
    if not token:
        return [], ""

    if is_http_url(token):
        if is_direct_video_url(token):
            return [{"url": token, "title": ""}], ""
        urls, creator_name = resolve_creator_urls(
            token,
            count=count,
            proxy=proxy,
            browser_cookies=browser_cookies,
            browser_wait=browser_wait,
            show_browser=show_browser,
            use_edge_profile=use_edge_profile,
            edge_profile_dir=edge_profile_dir,
        )
        return [{"url": url, "title": ""} for url in urls], creator_name

    if not platform:
        raise SystemExit("遇到 creator ID 但没有提供 --platform")
    page_url, inferred_platform = resolve_creator_input(
        creator_url="",
        creator_id=token,
        platform=platform,
        proxy=proxy,
        browser_cookies=browser_cookies,
    )
    urls, creator_name = resolve_creator_urls(
        page_url,
        count=count,
        proxy=proxy,
        browser_cookies=browser_cookies,
        browser_wait=browser_wait,
        show_browser=show_browser,
        use_edge_profile=use_edge_profile,
        edge_profile_dir=edge_profile_dir,
    )
    return [{"url": url, "title": ""} for url in urls], creator_name


def resolve_sources(
    sources: list[str],
    *,
    platform: str,
    count: int,
    proxy: str,
    hf_endpoint: str,
    browser_cookies: str,
    browser_wait: int,
    show_browser: bool,
    use_edge_profile: bool,
    edge_profile_dir: str,
) -> tuple[list[dict[str, str]], list[str]]:
    items: list[dict[str, str]] = []
    creator_names: list[str] = []

    for source in sources:
        source_path = Path(source)
        if source_path.exists():
            file_items = read_items(source_path)
            for file_item in file_items:
                expanded, creator_name = expand_source_token(
                    file_item["url"],
                    platform=platform,
                    count=count,
                    proxy=proxy,
                    hf_endpoint=hf_endpoint,
                    browser_cookies=browser_cookies,
                    browser_wait=browser_wait,
                    show_browser=show_browser,
                    use_edge_profile=use_edge_profile,
                    edge_profile_dir=edge_profile_dir,
                )
                for item in expanded:
                    item["title"] = file_item.get("title", "")
                items.extend(expanded)
                if creator_name:
                    creator_names.append(creator_name)
            continue

        expanded, creator_name = expand_source_token(
            source,
            platform=platform,
            count=count,
            proxy=proxy,
            hf_endpoint=hf_endpoint,
            browser_cookies=browser_cookies,
            browser_wait=browser_wait,
            show_browser=show_browser,
            use_edge_profile=use_edge_profile,
            edge_profile_dir=edge_profile_dir,
        )
        items.extend(expanded)
        if creator_name:
            creator_names.append(creator_name)

    return dedupe_items(items), creator_names


def run_extractor(
    extractor: Path,
    url: str,
    model: str,
    device: str,
    compute_type: str,
    beam_size: int,
    batch_size: int,
    proxy: str,
    hf_endpoint: str,
) -> tuple[int, dict[str, object], str]:
    cmd = [
        sys.executable,
        str(extractor),
        "--json",
        "--model",
        model,
        "--device",
        device,
        "--compute-type",
        compute_type,
        "--beam-size",
        str(beam_size),
        "--batch-size",
        str(batch_size),
    ]
    if proxy:
        cmd += ["--proxy", proxy]
    if hf_endpoint:
        cmd += ["--hf-endpoint", hf_endpoint]
    cmd.append(url)

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout = (proc.stdout or "").strip()
    payload: dict[str, object] = {}
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {}
    return proc.returncode, payload, (proc.stderr or "").strip()


def ensure_cuda_ready(device: str) -> None:
    if device != "cuda":
        raise SystemExit("只允许使用 GPU。请传 --device cuda，当前不允许 CPU 或 auto。")

    probe_code = """
import ctranslate2

supported = ctranslate2.get_supported_compute_types("cuda")
if not supported:
    raise SystemExit("ctranslate2 未检测到可用 CUDA 计算类型。")
print(",".join(supported))
""".strip()

    try:
        proc = subprocess.run(
            [sys.executable, "-c", probe_code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise SystemExit(f"无法执行 CUDA 检查：{exc}") from exc

    if proc.returncode != 0:
        details = (proc.stderr or proc.stdout or "").strip()
        if not details:
            details = "当前 Python 环境没有可用的 CUDA / ctranslate2 支持。"
        raise SystemExit(f"GPU 不可用，任务已退出。\n{details}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch extract transcripts from Douyin/Bilibili URLs, creator pages, or creator IDs.")
    parser.add_argument("sources", nargs="*", help="One or more TXT/CSV files, video URLs, creator page URLs, or creator IDs.")
    parser.add_argument("--creator", default="", help="Optional creator folder name override.")
    parser.add_argument("--creator-url", default="", help="Creator profile/page URL to crawl for video links.")
    parser.add_argument("--creator-id", default="", help="Creator ID/UID. Use with --platform.")
    parser.add_argument("--platform", default="", choices=["bilibili", "douyin"], help="Platform used with --creator-id.")
    parser.add_argument("--output-root", default=r"D:\视频文本", help="Root output directory.")
    parser.add_argument(
        "--extractor",
        default=str(Path(__file__).resolve().with_name("extract.py")),
        help="Path to the local extract.py script.",
    )
    parser.add_argument("--model", default="small", help="Whisper model: tiny/base/small/medium/large-v3/turbo.")
    parser.add_argument("--device", default="cuda", choices=["cuda"], help="Inference device. GPU only.")
    parser.add_argument(
        "--compute-type",
        default="float16",
        choices=["auto", "float16", "int8", "int8_float16"],
        help="Inference compute type.",
    )
    parser.add_argument("--beam-size", default=5, type=int, help="Beam size.")
    parser.add_argument("--batch-size", default=8, type=int, help="Batch size for GPU mode.")
    parser.add_argument("--count", "--limit", dest="count", default=0, type=int, help="Process only the first N URLs, 0 means all.")
    parser.add_argument("--proxy", default="", help="Optional HTTP proxy.")
    parser.add_argument("--hf-endpoint", default="", help="Optional Hugging Face mirror.")
    parser.add_argument(
        "--cookies-from-browser",
        default="",
        help="Optional browser cookie source for creator pages, for example chrome or edge:Default.",
    )
    parser.add_argument("--browser-wait", default=8, type=int, help="Seconds to wait for Douyin creator pages to render.")
    parser.add_argument("--show-browser", action="store_true", help="Show browser window while collecting Douyin creator pages.")
    parser.add_argument("--use-edge-profile", action="store_true", help="Reuse the local Edge signed-in profile for Douyin handle resolution.")
    parser.add_argument("--edge-profile-dir", default="Default", help="Edge profile directory name when using --use-edge-profile.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip output files that already exist.")
    parser.add_argument(
        "--simplified-only",
        action="store_true",
        default=True,
        help="Convert transcript text and extracted titles to simplified Chinese before saving.",
    )
    args = parser.parse_args()

    ensure_cuda_ready(args.device)

    extractor = Path(args.extractor).resolve()
    if not extractor.exists():
        raise SystemExit(f"Extractor not found: {extractor}")

    raw_sources = list(args.sources)
    if args.creator_url:
        raw_sources.append(args.creator_url)
    if args.creator_id:
        if not args.platform:
            raise SystemExit("--creator-id 需要同时提供 --platform")
        raw_sources.append(args.creator_id)
    if not raw_sources:
        raise SystemExit("No sources provided.")

    items, creator_names = resolve_sources(
        raw_sources,
        platform=args.platform,
        count=args.count,
        proxy=args.proxy,
        hf_endpoint=args.hf_endpoint,
        browser_cookies=args.cookies_from_browser,
        browser_wait=args.browser_wait,
        show_browser=args.show_browser,
        use_edge_profile=args.use_edge_profile,
        edge_profile_dir=args.edge_profile_dir,
    )

    creator_name = args.creator.strip()
    if not creator_name:
        creator_name = creator_names[0] if creator_names else "mixed-source"

    creator_dir = Path(args.output_root).resolve() / sanitize_filename(creator_name)
    creator_dir.mkdir(parents=True, exist_ok=True)

    total = len(items)
    for index, item in enumerate(items, start=1):
        url = item["url"]
        input_title = item.get("title", "")

        returncode, payload, stderr_text = run_extractor(
            extractor=extractor,
            url=url,
            model=args.model,
            device=args.device,
            compute_type=args.compute_type,
            beam_size=args.beam_size,
            batch_size=args.batch_size,
            proxy=args.proxy,
            hf_endpoint=args.hf_endpoint,
        )

        extracted_title = str(payload.get("title", "") or "")
        transcript_text = str(payload.get("text", "") or "")
        if args.simplified_only:
            extracted_title = to_simplified_chinese(extracted_title)
            transcript_text = to_simplified_chinese(transcript_text)
        stem = choose_stem(index, url, extracted_title, input_title)
        transcript_path = creator_dir / f"{stem}.txt"

        if args.skip_existing and transcript_path.exists():
            print(f"[{index}/{total}] skip: {transcript_path}")
            continue

        transcript_path.write_text(transcript_text, encoding="utf-8")

        if returncode == 0:
            print(f"[{index}/{total}] done: {transcript_path}")
        else:
            print(f"[{index}/{total}] empty-or-failed: {transcript_path}")
            if stderr_text:
                print(stderr_text, file=sys.stderr)

    print(f"Output: {creator_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
