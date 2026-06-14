"""视频文案提取工具 —— 支持 B站 / 抖音
策略：字幕优先（秒级），无字幕时下载音频用 Whisper 做语音识别。

用法:
  python extract.py "链接"
  python extract.py --model tiny "链接"     # 用轻量模型（更快但精度低）
  python extract.py --json "链接"           # JSON 输出
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# ── 全局代理设置 ──
PROXY: Optional[str] = None


def _proxy_env() -> dict:
    """返回代理环境变量"""
    if PROXY:
        return {"http_proxy": PROXY, "https_proxy": PROXY, "all_proxy": PROXY}
    return {}


def _env_with_proxy() -> dict:
    """合并系统环境变量 + 代理"""
    env = os.environ.copy()
    env.update(_proxy_env())
    return env


# ── 平台检测 ──


def detect_platform(url: str) -> str:
    """根据 URL 返回平台标识"""
    host = (urlparse(url).hostname or "").lower().replace("www.", "")
    if any(k in host for k in ("bilibili.com", "b23.tv")):
        return "bilibili"
    if any(k in host for k in ("douyin.com", "iesdouyin.com", "v.douyin.com")):
        return "douyin"
    raise ValueError(f"不支持的平台: {host}")


def extract_url(text: str) -> str:
    """从任意文本中自动提取第一个支持的视频链接（B站/抖音）"""
    patterns = [
        r"https?://v\.douyin\.com/[a-zA-Z0-9]+/?",
        r"https?://www\.douyin\.com/[^\s]+",
        r"https?://www\.iesdouyin\.com/[^\s]+",
        r"https?://www\.bilibili\.com/video/BV[a-zA-Z0-9]{10}[^\s]*",
        r"https?://b23\.tv/[a-zA-Z0-9]+[^\s]*",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            url = m.group(0).rstrip("\u3002\uff0c\u3001\uff1b\uff1a\uff01\uff1f\uff09\u201d\u2019\uff0e")
            return url
    return text.strip()


# ── B站 ──


def extract_bilibili(url: str) -> dict:
    """B站: 字幕优先 → API → 音频+Whisper"""
    try:
        r = _yt_dlp_extract(url, prefer_subs=True)
        if r["text"]:
            return r
    except Exception:
        pass

    try:
        r = _bilibili_api_extract(url)
        if r["text"]:
            return r
    except Exception:
        pass

    return _download_and_transcribe(url)


def _bilibili_api_extract(url: str) -> dict:
    """通过 B站公开 API 获取字幕和元数据"""
    import requests

    result = {"platform": "bilibili", "url": url, "method": "", "text": ""}

    bvid_match = re.search(r"BV[a-zA-Z0-9]{10}", url)
    if not bvid_match:
        if "b23.tv" in url:
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=False,
                timeout=10,
                proxies={"http": PROXY, "https": PROXY} if PROXY else None,
            )
            redirected = resp.headers.get("Location", url)
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
    result["tags"] = [t.get("tag_name", "") for t in (data.get("tags") or [])]

    cid = data.get("cid")
    if not cid:
        raise ValueError("未找到 cid")

    sub_url = f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}"
    sub_resp = requests.get(sub_url, headers=headers, proxies=proxy, timeout=15).json()
    subtitle_list = sub_resp.get("data", {}).get("subtitle", {}).get("subtitles", [])

    if subtitle_list:
        sub_json_url = None
        for sub in subtitle_list:
            if sub.get("lan_doc", "").startswith("中文"):
                sub_json_url = sub["subtitle_url"]
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


# ── 抖音 ──


def extract_douyin(url: str) -> dict:
    """抖音: 下载音频 → Whisper ASR"""
    return _download_and_transcribe(url)


# ── 通用: yt-dlp 提取 ──


def _yt_dlp_extract(url: str, prefer_subs: bool = True) -> dict:
    """用 yt-dlp 提取字幕文本"""
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
            url_arg = [url]
            try:
                subprocess.run(
                    cmd + url_arg,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
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
    """解析 SRT/VTT 字幕文件 → 纯文本"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

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


# ── 通用: 下载音频 + Whisper ──


def _download_and_transcribe(url: str) -> dict:
    """下载视频音频，用 Whisper 做语音识别"""
    platform = detect_platform(url)
    result = {"platform": platform, "url": url, "method": "whisper_asr", "text": ""}

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio")

        print("  ⏳ 正在下载音频...", file=sys.stderr)
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
            cmd + [url], capture_output=True, text=True, timeout=300, check=False
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
        print(f"  ⏳ Whisper 语音识别中... (文件: {size_mb:.1f}MB)", file=sys.stderr)

        text = _whisper_transcribe(audio_file)
        result["text"] = text
        result["method"] = "whisper_asr"

    return result


def _whisper_transcribe(audio_path: str, model_size: str = "medium") -> str:
    """Whisper 语音识别（优先 faster-whisper）"""
    try:
        from faster_whisper import WhisperModel

        device = "cuda" if _has_cuda() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"

        print(f"  📦 加载 Whisper 模型 ({model_size}, {device})...", file=sys.stderr)
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        segments, info = model.transcribe(audio_path, language="zh", beam_size=5)

        print(
            f"  📝 检测语言: {info.language} (概率: {info.language_probability:.2%})",
            file=sys.stderr,
        )

        lines = [seg.text.strip() for seg in segments]
        return "\n".join(lines)

    except ImportError:
        import whisper

        print(f"  📦 加载原版 Whisper ({model_size})...", file=sys.stderr)
        model = whisper.load_model(model_size)
        result = model.transcribe(audio_path, language="zh")
        return result["text"]


def _has_cuda() -> bool:
    """检测 CUDA 是否可用（优先用 ctranslate2，回退 torch）"""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        try:
            import torch

            return torch.cuda.is_available()
        except ImportError:
            return False


# ── 主入口 ──


EXTRACTORS = {
    "bilibili": extract_bilibili,
    "douyin": extract_douyin,
}


def extract(url: str, output_json: bool = False, model: str = "medium") -> dict:
    """主函数: 输入链接，返回提取结果"""
    platform = detect_platform(url)
    print(f"\U0001f50d 平台: {platform}", file=sys.stderr)
    print(f"\U0001f517 链接: {url}", file=sys.stderr)

    extractor = EXTRACTORS[platform]

    import __main__

    original = _whisper_transcribe

    def _with_model(path, size=model):
        return original(path, size)

    __main__._whisper_transcribe = _with_model

    try:
        result = extractor(url)

        if output_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print()
            print("=" * 60)
            if result.get("title"):
                print(f"\U0001f4cc 标题: {result['title']}")
            if result.get("description"):
                print(f"\U0001f4dd 简介: {result['description'][:200]}")
            if result.get("tags"):
                print(f"\U0001f3f7\ufe0f  标签: {', '.join(result['tags'][:10])}")
            print(f"\u2699\ufe0f  提取方式: {result['method']}")
            if result.get("language"):
                print(f"\U0001f310 语言: {result['language']}")
            print("=" * 60)
            print()
            print(result.get("text", result.get("error", "（无内容）")))

        return result
    finally:
        __main__._whisper_transcribe = original


def main():
    parser = argparse.ArgumentParser(
        description="视频文案提取 —— B站 / 抖音",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python extract.py "https://www.bilibili.com/video/BV1xx411c7mD"
  python extract.py "https://v.douyin.com/xxxxx/"
  python extract.py --json "https://..." > result.json
        """,
    )
    parser.add_argument("text", help="视频链接或抖音/B站分享文本（自动提取链接）")
    parser.add_argument("--proxy", default=None, help="HTTP 代理地址 (如 http://127.0.0.1:7890)")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument(
        "--model",
        default="medium",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper 模型大小 (默认 medium)",
    )
    args = parser.parse_args()

    global PROXY
    PROXY = args.proxy

    raw = args.text
    url = extract_url(raw)
    if url != raw.strip():
        print(f"\U0001f50e 从文本中提取链接: {url}", file=sys.stderr)
    extract(url, output_json=args.json, model=args.model)


if __name__ == "__main__":
    main()
