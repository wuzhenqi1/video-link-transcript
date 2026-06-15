"""视频文案提取工具 —— 支持 B站 / 抖音
策略：字幕优先（秒级），无字幕时下载音频用 Whisper 做语音识别。

用法:
  python extract.py "链接"
  python extract.py --model tiny "链接"
  python extract.py --json "链接"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import site
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

PROXY: Optional[str] = None
DEFAULT_DEVICE = "cuda"
DEFAULT_COMPUTE_TYPE = "float16"
DEFAULT_BEAM_SIZE = 5
DEFAULT_BATCH_SIZE = 1
DEFAULT_HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "").strip()


def _proxy_env() -> dict:
    if PROXY:
        return {"http_proxy": PROXY, "https_proxy": PROXY, "all_proxy": PROXY}
    return {}


def _env_with_proxy() -> dict:
    env = os.environ.copy()
    env.update(_proxy_env())
    return env


def _configure_windows_cuda_dll_path() -> None:
    if os.name != "nt":
        return

    dll_dirs = []
    candidate_roots = []
    try:
        candidate_roots.extend(site.getsitepackages())
    except Exception:
        pass
    user_site = site.getusersitepackages()
    if user_site:
        candidate_roots.append(user_site)

    for root in candidate_roots:
        nvidia_root = Path(root) / "nvidia"
        for subdir in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
            bin_dir = nvidia_root / subdir / "bin"
            if bin_dir.exists():
                dll_dirs.append(str(bin_dir))

    for dll_dir in dll_dirs:
        try:
            os.add_dll_directory(dll_dir)
        except (AttributeError, FileNotFoundError):
            pass

    if dll_dirs:
        existing_path = os.environ.get("PATH", "")
        prefix = os.pathsep.join(dll_dirs)
        os.environ["PATH"] = prefix + os.pathsep + existing_path if existing_path else prefix


def _configure_hf_endpoint() -> None:
    if DEFAULT_HF_ENDPOINT:
        os.environ["HF_ENDPOINT"] = DEFAULT_HF_ENDPOINT
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().replace("www.", "")
    if any(k in host for k in ("bilibili.com", "b23.tv")):
        return "bilibili"
    if any(k in host for k in ("douyin.com", "iesdouyin.com", "v.douyin.com")):
        return "douyin"
    raise ValueError(f"不支持的平台: {host}")


def extract_url(text: str) -> str:
    patterns = [
        r"https?://v\.douyin\.com/[a-zA-Z0-9_-]+/?",
        r"https?://www\.douyin\.com/[^\s]+",
        r"https?://www\.iesdouyin\.com/[^\s]+",
        r"https?://www\.bilibili\.com/video/BV[a-zA-Z0-9]{10}[^\s]*",
        r"https?://b23\.tv/[a-zA-Z0-9]+[^\s]*",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0).rstrip("\u3002\uff0c\u3001\uff1b\uff1a\uff01\uff1f\uff09\u201d\u2019\uff0e")
    return text.strip()


def extract_bilibili(url: str) -> dict:
    try:
        result = _yt_dlp_extract(url, prefer_subs=True)
        if result["text"]:
            return result
    except Exception:
        pass

    try:
        result = _bilibili_api_extract(url)
        if result["text"]:
            return result
    except Exception:
        pass

    return _download_and_transcribe(url)


def _bilibili_api_extract(url: str) -> dict:
    import requests

    result = {"platform": "bilibili", "url": url, "method": "", "text": ""}

    bvid_match = re.search(r"BV[a-zA-Z0-9]{10}", url)
    if not bvid_match and "b23.tv" in url:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=False,
            timeout=10,
            proxies={"http": PROXY, "https": PROXY} if PROXY else None,
        )
        redirected = response.headers.get("Location", url)
        bvid_match = re.search(r"BV[a-zA-Z0-9]{10}", redirected)

    if not bvid_match:
        raise ValueError("无法提取 BVID")

    bvid = bvid_match.group(0)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
    }
    proxy = {"http": PROXY, "https": PROXY} if PROXY else None

    info_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    info_resp = requests.get(info_url, headers=headers, proxies=proxy, timeout=15).json()
    if info_resp.get("code") != 0:
        raise ValueError(f"B站 API 错误: {info_resp.get('message')}")

    data = info_resp["data"]
    result["title"] = data.get("title", "")
    result["description"] = data.get("desc", "")
    result["tags"] = [tag.get("tag_name", "") for tag in (data.get("tags") or [])]

    cid = data.get("cid")
    if not cid:
        raise ValueError("未找到 cid")

    sub_url = f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}"
    sub_resp = requests.get(sub_url, headers=headers, proxies=proxy, timeout=15).json()
    subtitle_list = sub_resp.get("data", {}).get("subtitle", {}).get("subtitles", [])

    if subtitle_list:
        sub_json_url = None
        for subtitle in subtitle_list:
            if subtitle.get("lan_doc", "").startswith("中文"):
                sub_json_url = subtitle["subtitle_url"]
                break
        if not sub_json_url:
            sub_json_url = subtitle_list[0]["subtitle_url"]

        if sub_json_url.startswith("//"):
            sub_json_url = "https:" + sub_json_url

        sub_data = requests.get(sub_json_url, headers=headers, proxies=proxy, timeout=15).json()
        lines = [item.get("content", "") for item in sub_data.get("body", [])]
        result["text"] = "\n".join(lines)
        result["method"] = "bilibili_captions"

    return result


def extract_douyin(url: str) -> dict:
    return _download_and_transcribe(url)


def _yt_dlp_extract(url: str, prefer_subs: bool = True) -> dict:
    result = {"platform": detect_platform(url), "url": url, "method": "", "text": ""}

    with tempfile.TemporaryDirectory() as tmpdir:
        if prefer_subs:
            cmd = [
                sys.executable,
                "-m",
                "yt_dlp",
                "--skip-download",
                "--write-auto-subs",
                "--write-subs",
                "--sub-langs",
                "zh-Hans,zh-CN,zh,zh-Hant,zh-TW,en",
                "--sub-format",
                "vtt",
                "--convert-subs",
                "srt",
                "-o",
                f"{tmpdir}/%(id)s.%(ext)s",
            ]
            if detect_platform(url) == "bilibili":
                cmd += [
                    "--add-header",
                    "Referer:https://www.bilibili.com/",
                    "--add-header",
                    "Origin:https://www.bilibili.com",
                ]
            if PROXY:
                cmd += ["--proxy", PROXY]

            try:
                subprocess.run(
                    cmd + [url],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                    env=_env_with_proxy(),
                )
                sub_files = list(Path(tmpdir).glob("*.srt")) + list(Path(tmpdir).glob("*.vtt"))
                if sub_files:
                    text = _parse_subtitle_file(str(sub_files[0]))
                    if text.strip():
                        result["text"] = text
                        result["method"] = "yt_dlp_subs"
                        return result
            except Exception:
                pass

    return result


def _parse_subtitle_file(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as handle:
        content = handle.read()

    lines = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\d+$", line):
            continue
        if "-->" in line or re.match(r"^\d{2}:\d{2}:", line):
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and not line.startswith("NOTE"):
            lines.append(line)

    return "\n".join(lines)


def _download_and_transcribe(url: str) -> dict:
    platform = detect_platform(url)
    result = {"platform": platform, "url": url, "method": "whisper_asr", "text": ""}

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio")

        print("  正在下载音频...", file=sys.stderr)
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "-x",
            "--audio-format",
            "wav",
            "--audio-quality",
            "0",
            "-o",
            f"{audio_path}.%(ext)s",
            "--no-playlist",
            "--no-warnings",
        ]

        if PROXY:
            cmd += ["--proxy", PROXY]

        if platform == "bilibili":
            cmd += [
                "--add-header",
                "Referer:https://www.bilibili.com/",
                "--add-header",
                "Origin:https://www.bilibili.com",
            ]
        elif platform == "douyin":
            cmd += ["--cookies-from-browser", "chrome"]

        proc = subprocess.run(
            cmd + [url],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            env=_env_with_proxy(),
        )

        if proc.returncode != 0:
            stderr_tail = (proc.stderr or "")[-300:]
            result["error"] = f"下载失败: {stderr_tail}"
            return result

        audio_files = (
            list(Path(tmpdir).glob("audio.wav"))
            + list(Path(tmpdir).glob("audio.m4a"))
            + list(Path(tmpdir).glob("audio.mp3"))
            + list(Path(tmpdir).glob("audio.*"))
        )
        if not audio_files:
            result["error"] = "未找到下载的音频文件"
            return result

        audio_file = str(audio_files[0])
        size_mb = os.path.getsize(audio_file) / 1024 / 1024
        print(f"  Whisper 语音识别中... (文件: {size_mb:.1f}MB)", file=sys.stderr)

        result["text"] = _whisper_transcribe(audio_file)
        result["method"] = "whisper_asr"

    return result


def _resolve_compute_type(device: str, compute_type: str) -> str:
    if compute_type != "auto":
        return compute_type
    if device == "cuda":
        return "float16"
    return "int8"


def _ensure_cuda() -> None:
    try:
        _configure_windows_cuda_dll_path()
        import ctranslate2

        if ctranslate2.get_cuda_device_count() <= 0:
            raise SystemExit("GPU 不可用，任务已退出。")
    except ImportError as exc:
        raise SystemExit("缺少 ctranslate2，无法执行 GPU 转写。") from exc


def _whisper_transcribe(audio_path: str, model_size: str = "medium") -> str:
    _ensure_cuda()
    _configure_hf_endpoint()

    try:
        from faster_whisper import BatchedInferencePipeline, WhisperModel
    except ImportError as exc:
        raise SystemExit("缺少 faster-whisper，无法执行 GPU 转写。") from exc

    compute_type = _resolve_compute_type(DEFAULT_DEVICE, DEFAULT_COMPUTE_TYPE)
    print(f"  加载 Whisper 模型 ({model_size}, {DEFAULT_DEVICE})...", file=sys.stderr)
    model = WhisperModel(model_size, device=DEFAULT_DEVICE, compute_type=compute_type)
    transcriber = model
    transcribe_kwargs = {
        "language": "zh",
        "beam_size": DEFAULT_BEAM_SIZE,
    }
    if DEFAULT_BATCH_SIZE > 1:
        transcriber = BatchedInferencePipeline(model=model)
        transcribe_kwargs["batch_size"] = DEFAULT_BATCH_SIZE
    segments, info = transcriber.transcribe(audio_path, **transcribe_kwargs)

    print(
        f"  检测语言: {info.language} (概率: {info.language_probability:.2%})",
        file=sys.stderr,
    )
    return "\n".join(seg.text.strip() for seg in segments)


EXTRACTORS = {
    "bilibili": extract_bilibili,
    "douyin": extract_douyin,
}


def extract(
    url: str,
    output_json: bool = False,
    model: str = "medium",
    device: str = "cuda",
    compute_type: str = "float16",
    beam_size: int = 5,
    batch_size: int = 1,
) -> dict:
    platform = detect_platform(url)
    print(f"平台: {platform}", file=sys.stderr)
    print(f"链接: {url}", file=sys.stderr)

    extractor = EXTRACTORS[platform]

    global DEFAULT_DEVICE, DEFAULT_COMPUTE_TYPE, DEFAULT_BEAM_SIZE, DEFAULT_BATCH_SIZE
    original_device = DEFAULT_DEVICE
    original_compute_type = DEFAULT_COMPUTE_TYPE
    original_beam_size = DEFAULT_BEAM_SIZE
    original_batch_size = DEFAULT_BATCH_SIZE

    DEFAULT_DEVICE = device
    DEFAULT_COMPUTE_TYPE = compute_type
    DEFAULT_BEAM_SIZE = beam_size
    DEFAULT_BATCH_SIZE = batch_size

    try:
        result = extractor(url)
        if output_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print()
            print("=" * 60)
            if result.get("title"):
                print(f"标题: {result['title']}")
            if result.get("description"):
                print(f"简介: {result['description'][:200]}")
            if result.get("tags"):
                print(f"标签: {', '.join(result['tags'][:10])}")
            print(f"提取方式: {result['method']}")
            print("=" * 60)
            print()
            print(result.get("text", result.get("error", "（无内容）")))
        return result
    finally:
        DEFAULT_DEVICE = original_device
        DEFAULT_COMPUTE_TYPE = original_compute_type
        DEFAULT_BEAM_SIZE = original_beam_size
        DEFAULT_BATCH_SIZE = original_batch_size


def main() -> None:
    parser = argparse.ArgumentParser(
        description="视频文案提取 —— B站 / 抖音",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python extract.py "<video-url>"
  python extract.py --json "<video-url>"
        """,
    )
    parser.add_argument("text", help="视频链接或抖音/B站分享文本（自动提取链接）")
    parser.add_argument("--proxy", default=None, help="HTTP 代理地址 (如 http://127.0.0.1:7890)")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument(
        "--model",
        default="medium",
        choices=["tiny", "base", "small", "medium", "large-v3", "turbo"],
        help="Whisper 模型大小 (默认 medium)",
    )
    parser.add_argument(
        "--device",
        default="cuda",
        choices=["cuda"],
        help="推理设备，仅支持 GPU",
    )
    parser.add_argument(
        "--compute-type",
        default="float16",
        choices=["auto", "float16", "int8", "int8_float16"],
        help="推理精度 (默认 float16)",
    )
    parser.add_argument(
        "--beam-size",
        default=5,
        type=int,
        help="解码 beam size，越小越快 (默认 5)",
    )
    parser.add_argument(
        "--batch-size",
        default=1,
        type=int,
        help="批量转写大小，GPU 上可适当调大 (默认 1)",
    )
    parser.add_argument(
        "--hf-endpoint",
        default="",
        help="Hugging Face 镜像地址，如 https://hf-mirror.com",
    )
    args = parser.parse_args()

    global PROXY, DEFAULT_HF_ENDPOINT
    PROXY = args.proxy
    if args.hf_endpoint:
        DEFAULT_HF_ENDPOINT = args.hf_endpoint

    raw = args.text
    url = extract_url(raw)
    if url != raw.strip():
        print(f"从文本中提取链接: {url}", file=sys.stderr)
    extract(
        url,
        output_json=args.json,
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
        beam_size=args.beam_size,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
