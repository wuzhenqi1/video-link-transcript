#!/usr/bin/env python3
"""Collect public video URLs from creator pages, creator IDs, or a single video URL."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlparse

import yt_dlp


DOUYIN_VIDEO_RE = re.compile(
    r"https?://(?:www\.)?(?:douyin\.com/(?:video|share/video)/|iesdouyin\.com/video/)(\d+)",
    re.IGNORECASE,
)
DOUYIN_SHORT_RE = re.compile(r"https?://v\.douyin\.com/[a-zA-Z0-9_-]+/?", re.IGNORECASE)
DOUYIN_USER_URL_RE = re.compile(r"https?://www\.douyin\.com/user/([^/?#]+)", re.IGNORECASE)
DOUYIN_SEC_UID_RE = re.compile(r"^MS4wLjABAAAA[\w-]+$")
BILIBILI_VIDEO_RE = re.compile(r"BV[a-zA-Z0-9]{10}")
ANY_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def sanitize_filename(name: str, max_len: int = 120) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if not name:
        return "untitled"
    return name[:max_len].rstrip()


def dedupe_urls(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


def parse_browser_tuple(value: str) -> tuple[str, ...]:
    raw = [part.strip() for part in value.split(":") if part.strip()]
    if not raw:
        raise SystemExit("--cookies-from-browser 不能为空")
    return tuple(raw)


def resolve_chrome_executable() -> str:
    env_path = os.environ.get("CHROME_EXECUTABLE_PATH", "").strip()
    candidates = [
        env_path,
        str(Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).expanduser().exists():
            return str(Path(candidate).expanduser())

    for name in ("chrome.exe", "chrome", "google-chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found

    return ""


def resolve_edge_user_data_dir() -> str:
    candidates = [
        str(Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data"),
        os.environ.get("EDGE_USER_DATA_DIR", "").strip(),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).expanduser().exists():
            return str(Path(candidate).expanduser())
    return ""


def extract_first_url(text: str) -> str:
    match = ANY_URL_RE.search(text.strip())
    return match.group(0) if match else text.strip()


def build_ydl_opts(proxy: str, browser_cookies: str) -> dict[str, object]:
    opts: dict[str, object] = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "noplaylist": False,
    }
    if proxy:
        opts["proxy"] = proxy
    if browser_cookies:
        opts["cookiesfrombrowser"] = parse_browser_tuple(browser_cookies)
    return opts


def extract_creator_entries(page_url: str, proxy: str, browser_cookies: str) -> dict[str, object]:
    attempts = [browser_cookies]
    if not browser_cookies and "bilibili.com" in page_url.lower():
        attempts.append("chrome")

    last_exc: Exception | None = None
    for cookie_source in attempts:
        ydl_opts = build_ydl_opts(proxy=proxy, browser_cookies=cookie_source)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(page_url, download=False)
        except Exception as exc:
            last_exc = exc
            continue
        if not isinstance(info, dict):
            continue
        return info

    raise SystemExit(
        f"无法解析创作者页面: {page_url}\n"
        f"原因: {last_exc}\n"
        "可尝试传入 --cookies-from-browser chrome，或直接提供公开视频链接。"
    ) from last_exc


def creator_name_from_info(info: dict[str, object], fallback: str) -> str:
    return (
        str(info.get("uploader") or "").strip()
        or str(info.get("channel") or "").strip()
        or str(info.get("title") or "").strip()
        or sanitize_filename(fallback, max_len=80)
    )


def urls_from_entries(info: dict[str, object], count: int) -> list[str]:
    entries = info.get("entries") or []
    urls: list[str] = []

    for entry in entries:
        if not entry:
            continue

        candidate = str(entry.get("webpage_url") or entry.get("url") or "").strip()
        entry_id = str(entry.get("id") or "").strip()

        if candidate.startswith(("http://", "https://")):
            urls.append(candidate)
        elif re.fullmatch(r"BV[a-zA-Z0-9]{10}", candidate):
            urls.append(f"https://www.bilibili.com/video/{candidate}")
        elif re.fullmatch(r"BV[a-zA-Z0-9]{10}", entry_id):
            urls.append(f"https://www.bilibili.com/video/{entry_id}")
        elif candidate.isdigit():
            urls.append(f"https://www.douyin.com/video/{candidate}")
        elif entry_id.isdigit():
            urls.append(f"https://www.douyin.com/video/{entry_id}")

        if count > 0 and len(urls) >= count:
            break

    urls = dedupe_urls(urls)
    if not urls:
        raise SystemExit(
            "没有解析到公开视频链接。\n"
            "这通常是页面未公开枚举、触发风控，或需要登录态。"
        )
    return urls[:count] if count > 0 else urls


def normalize_douyin_video_url(url: str) -> str:
    match = DOUYIN_VIDEO_RE.search(url.strip())
    if not match:
        return url.strip()
    return f"https://www.douyin.com/video/{match.group(1)}"


def extract_douyin_sec_uid_from_url(url: str) -> str:
    match = DOUYIN_USER_URL_RE.search(url.strip())
    return match.group(1) if match else ""


def build_creator_home_url(platform: str, creator_id: str) -> str:
    platform = platform.lower().strip()
    creator_id = creator_id.strip()
    if platform == "bilibili":
        return f"https://space.bilibili.com/{creator_id}/video"
    if platform == "douyin":
        if DOUYIN_SEC_UID_RE.fullmatch(creator_id):
            return f"https://www.douyin.com/user/{creator_id}"
        handle = creator_id.lstrip("@").strip()
        if not handle:
            raise SystemExit("抖音 creator-id 不能为空")
        return f"https://www.douyin.com/search/{quote(handle, safe='')}?type=user"
    raise SystemExit("creator ID 模式只支持 bilibili 或 douyin")


def resolve_short_url(url: str, proxy: str, browser_cookies: str) -> str:
    url = extract_first_url(url)
    ydl_opts = build_ydl_opts(proxy=proxy, browser_cookies=browser_cookies)
    ydl_opts["extract_flat"] = False
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url.strip(), download=False)
    except Exception:
        return url.strip()

    if isinstance(info, dict):
        webpage_url = str(info.get("webpage_url") or "").strip()
        if webpage_url:
            return webpage_url
    return url.strip()


def resolve_douyin_video_url(url: str, proxy: str, browser_cookies: str) -> str:
    raw = url.strip()
    short_match = DOUYIN_SHORT_RE.search(raw)
    if short_match:
        url = resolve_short_url(short_match.group(0), proxy=proxy, browser_cookies=browser_cookies)
    else:
        url = extract_first_url(raw)
    return normalize_douyin_video_url(url)


async def collect_douyin_public_video_urls_async(
    *,
    page_url: str,
    count: int,
    browser_cookies: str,
    browser_wait: int,
    headless: bool,
    use_edge_profile: bool,
    edge_profile_dir: str,
) -> tuple[list[str], str]:
    from playwright.async_api import async_playwright

    chrome_executable = resolve_chrome_executable()
    if not chrome_executable:
        raise SystemExit(
            "没有找到本机 Chrome。\n"
            "请先安装 Chrome，或者设置 CHROME_EXECUTABLE_PATH。"
        )

    browser_args = ["--disable-blink-features=AutomationControlled"]
    async with async_playwright() as p:
        if use_edge_profile:
            user_data_dir = resolve_edge_user_data_dir()
            if not user_data_dir:
                raise SystemExit(
                    "没有找到 Edge 用户数据目录。\n"
                    "请确认本机已安装 Edge 并登录过。"
                )
            if edge_profile_dir.strip():
                browser_args.append(f"--profile-directory={edge_profile_dir.strip()}")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="msedge",
                headless=headless,
                viewport={"width": 1440, "height": 1000},
                locale="zh-CN",
                args=browser_args,
            )
            browser = None
        else:
            browser = await p.chromium.launch(
                headless=headless,
                executable_path=chrome_executable,
                args=browser_args,
            )
            context = await browser.new_context(
                viewport={"width": 1440, "height": 1000},
                locale="zh-CN",
            )
        try:
            try:
                if browser_cookies:
                    await load_browser_cookies_into_context(context, browser_cookies)

                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(max(1000, browser_wait * 1000))

                resolved_url, creator_name = await resolve_douyin_profile_if_needed(
                    page=page,
                    browser_wait=browser_wait,
                    headless=headless,
                    target_label=page_url.rsplit("/", 1)[-1].split("?")[0],
                )
                if resolved_url and resolved_url != page.url:
                    await page.goto(resolved_url, wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(max(1000, browser_wait * 1000))

                last_count = -1
                stable_rounds = 0
                max_rounds = max(4, count * 3 if count > 0 else 12)

                for _ in range(max_rounds):
                    urls = await extract_douyin_video_urls_from_page(page)
                    current = len(urls)
                    if count > 0 and current >= count:
                        break
                    if current == last_count:
                        stable_rounds += 1
                    else:
                        stable_rounds = 0
                    if stable_rounds >= 3:
                        break
                    last_count = current
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(2000)

                title = (await page.title()).strip()
                creator_name = creator_name or title.replace("的抖音 - 抖音", "").strip() or sanitize_filename(
                    urlparse(page.url).path.rsplit("/", 1)[-1],
                    max_len=80,
                )
                urls = await extract_douyin_video_urls_from_page(page)

                if not urls:
                    raise SystemExit(
                        "抖音作者页没有抓到公开视频链接。\n"
                        "请确认输入的是正确作者主页链接、sec_uid，或抖音号；必要时加 --cookies-from-browser chrome。"
                    )

                return (urls[:count] if count > 0 else urls), creator_name
            finally:
                await context.close()
        finally:
            if browser is not None:
                await browser.close()


async def extract_douyin_video_urls_from_page(page) -> list[str]:
    hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(el => el.href)")
    html = await page.content()

    urls: list[str] = []
    for href in hrefs:
        match = DOUYIN_VIDEO_RE.search(str(href))
        if match:
            urls.append(f"https://www.douyin.com/video/{match.group(1)}")

    for aweme_id in re.findall(r"/video/(\d+)", html):
        urls.append(f"https://www.douyin.com/video/{aweme_id}")

    return dedupe_urls(urls)


async def extract_douyin_user_candidates(page) -> list[dict[str, str]]:
    return await page.eval_on_selector_all(
        "a[href]",
        r"""els => els.map(el => ({
            href: el.href || "",
            text: (el.innerText || el.textContent || "").trim(),
            aria: (el.getAttribute("aria-label") || "").trim(),
            title: (el.getAttribute("title") || "").trim()
        }))""",
    )


async def extract_douyin_user_urls_from_page(page) -> list[str]:
    html = await page.content()
    candidates = await extract_douyin_user_candidates(page)

    urls: list[str] = []
    for item in candidates:
        href = str(item.get("href") or "")
        match = DOUYIN_USER_URL_RE.search(href)
        if match:
            urls.append(f"https://www.douyin.com/user/{match.group(1)}")

    for sec_uid in re.findall(r"https://www\.douyin\.com/user/(MS4wLjABAAAA[\w-]+)", html):
        urls.append(f"https://www.douyin.com/user/{sec_uid}")

    return dedupe_urls(urls)


async def resolve_douyin_profile_if_needed(page, browser_wait: int, headless: bool, target_label: str) -> tuple[str, str]:
    page_url = page.url
    if "/search/" not in page_url:
        return page_url, ""

    if "type=user" not in page_url:
        return page_url, ""

    last_seen = ""
    rounds = max(3, browser_wait)
    for _ in range(rounds):
        candidates = await extract_douyin_user_candidates(page)
        matched_urls: list[str] = []
        matched_name = ""

        for item in candidates:
            href = str(item.get("href") or "")
            match = DOUYIN_USER_URL_RE.search(href)
            if not match:
                continue
            url = f"https://www.douyin.com/user/{match.group(1)}"
            text = " ".join(
                part
                for part in [str(item.get("text") or ""), str(item.get("aria") or ""), str(item.get("title") or "")]
                if part
            )
            if target_label.lower() in text.lower() or target_label.lower() in url.lower():
                matched_urls.append(url)
                if text.strip():
                    matched_name = text.strip()

        if matched_urls:
            candidate = matched_urls[0]
            if candidate != last_seen:
                last_seen = candidate
                await page.wait_for_timeout(1000)
                continue
            title = (await page.title()).strip()
            creator_name = matched_name or title.replace("抖音搜索", "").replace("-", " ").strip()
            return candidate, creator_name
        await page.wait_for_timeout(1000)

    user_urls = await extract_douyin_user_urls_from_page(page)
    if user_urls:
        return user_urls[0], ""

    raise SystemExit(
        "无法从抖音搜索结果里定位作者主页。\n"
        "请直接提供作者主页链接、sec_uid，或者再试一次带 --cookies-from-browser chrome。"
    )


async def load_browser_cookies_into_context(context, browser_cookies: str) -> None:
    import browser_cookie3

    browser_name = parse_browser_tuple(browser_cookies)[0].lower()
    loader = getattr(browser_cookie3, browser_name, None)
    if loader is None:
        raise SystemExit(f"不支持的 cookies 浏览器: {browser_name}")

    jar = loader(domain_name="douyin.com")
    cookie_params: list[dict[str, object]] = []
    for cookie in jar:
        if "douyin.com" not in (cookie.domain or ""):
            continue
        domain = (cookie.domain or "").lstrip(".")
        cookie_params.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": domain,
                "path": cookie.path or "/",
                "secure": bool(cookie.secure),
                "httpOnly": bool(getattr(cookie, "_rest", {}).get("HTTPOnly")),
            }
        )
    if cookie_params:
        await context.add_cookies(cookie_params)


def collect_douyin_public_video_urls(
    *,
    page_url: str,
    count: int,
    browser_cookies: str,
    browser_wait: int,
    headless: bool,
    use_edge_profile: bool,
    edge_profile_dir: str,
) -> tuple[list[str], str]:
    attempts: list[tuple[bool, int]] = [(headless, browser_wait)]
    if headless:
        attempts.append((False, max(browser_wait, 15)))
    else:
        attempts.append((False, max(browser_wait, 15)))

    last_error: Exception | None = None
    for attempt_headless, attempt_wait in attempts:
        try:
            return asyncio.run(
                collect_douyin_public_video_urls_async(
                    page_url=page_url,
                    count=count,
                    browser_cookies=browser_cookies,
                    browser_wait=attempt_wait,
                    headless=attempt_headless,
                    use_edge_profile=use_edge_profile,
                    edge_profile_dir=edge_profile_dir,
                )
            )
        except SystemExit as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise SystemExit(str(last_error))

    raise SystemExit(
        "抖音作者页抓取失败，请改用作者主页链接、sec_uid，或加 --cookies-from-browser chrome。"
    )


async def resolve_douyin_sec_uid_from_video_async(
    *,
    video_url: str,
    browser_cookies: str,
    browser_wait: int,
    headless: bool,
) -> tuple[str, str]:
    from playwright.async_api import async_playwright

    chrome_executable = resolve_chrome_executable()
    if not chrome_executable:
        raise SystemExit(
            "没有找到本机 Chrome。\n"
            "请先安装 Chrome，或者设置 CHROME_EXECUTABLE_PATH。"
        )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            executable_path=chrome_executable,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                viewport={"width": 1440, "height": 1000},
                locale="zh-CN",
            )
            try:
                if browser_cookies:
                    await load_browser_cookies_into_context(context, browser_cookies)

                page = await context.new_page()
                await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(max(1000, browser_wait * 1000))

                title = (await page.title()).strip()
                hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(el => el.href)")
                html = await page.content()

                candidates: list[str] = []
                for href in hrefs:
                    sec_uid = extract_douyin_sec_uid_from_url(str(href))
                    if DOUYIN_SEC_UID_RE.fullmatch(sec_uid):
                        candidates.append(sec_uid)
                for sec_uid in re.findall(r"https://www\.douyin\.com/user/(MS4wLjABAAAA[\w-]+)", html):
                    candidates.append(sec_uid)

                candidates = dedupe_urls(candidates)
                if not candidates:
                    raise SystemExit(
                        "无法从抖音视频页反查作者 sec_uid。\n"
                        "请改用作者主页链接或正确的抖音号。"
                    )

                return candidates[0], title
            finally:
                await context.close()
        finally:
            await browser.close()


def resolve_douyin_sec_uid_from_video(
    *,
    video_url: str,
    browser_cookies: str,
    browser_wait: int,
    headless: bool,
) -> tuple[str, str]:
    return asyncio.run(
        resolve_douyin_sec_uid_from_video_async(
            video_url=video_url,
            browser_cookies=browser_cookies,
            browser_wait=browser_wait,
            headless=headless,
        )
    )


def resolve_creator_input(
    creator_url: str,
    creator_id: str,
    platform: str,
    proxy: str,
    browser_cookies: str,
) -> tuple[str, str]:
    if creator_url:
        creator_url = creator_url.strip()
        if "douyin.com" in creator_url:
            creator_url = resolve_douyin_video_url(creator_url, proxy=proxy, browser_cookies=browser_cookies)
            if DOUYIN_VIDEO_RE.search(creator_url):
                sec_uid, _ = resolve_douyin_sec_uid_from_video(
                    video_url=creator_url,
                    browser_cookies=browser_cookies,
                    browser_wait=8,
                    headless=True,
                )
                return f"https://www.douyin.com/user/{sec_uid}", "douyin"
            sec_uid = extract_douyin_sec_uid_from_url(creator_url)
            if sec_uid:
                return f"https://www.douyin.com/user/{sec_uid}", "douyin"
        return creator_url, platform.strip().lower()

    if creator_id:
        if not platform:
            raise SystemExit("--creator-id 需要同时提供 --platform")
        return build_creator_home_url(platform, creator_id), platform.strip().lower()

    raise SystemExit("需要提供 --creator-url 或 --creator-id")


def collect_urls(
    *,
    page_url: str,
    platform: str,
    count: int,
    proxy: str,
    browser_cookies: str,
    browser_wait: int,
    headless: bool,
    use_edge_profile: bool,
    edge_profile_dir: str,
) -> tuple[list[str], str]:
    if platform == "douyin" or "douyin.com" in page_url:
        return collect_douyin_public_video_urls(
            page_url=page_url,
            count=count,
            browser_cookies=browser_cookies,
            browser_wait=browser_wait,
            headless=headless,
            use_edge_profile=use_edge_profile,
            edge_profile_dir=edge_profile_dir,
        )

    info = extract_creator_entries(page_url=page_url, proxy=proxy, browser_cookies=browser_cookies)
    fallback_name = page_url.rsplit("/", 1)[-1]
    creator_name = creator_name_from_info(info, fallback=fallback_name)
    urls = urls_from_entries(info, count=args_count(count))
    return urls, creator_name


def args_count(count: int) -> int:
    return count if count > 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public video URLs from Douyin or Bilibili creator pages.")
    parser.add_argument("--creator-url", default="", help="Creator profile/page URL, or one Douyin video URL.")
    parser.add_argument("--creator-id", default="", help="Creator ID/UID. Douyin only supports sec_uid here.")
    parser.add_argument("--platform", default="", choices=["bilibili", "douyin"], help="Platform used with --creator-id.")
    parser.add_argument("--count", "--limit", dest="count", default=0, type=int, help="Collect only the first N URLs, 0 means all.")
    parser.add_argument("--proxy", default="", help="Optional HTTP proxy.")
    parser.add_argument(
        "--cookies-from-browser",
        default="",
        help="Optional browser cookie source, for example chrome or edge:Default.",
    )
    parser.add_argument("--creator-name", default="", help="Optional creator name override for the output file name.")
    parser.add_argument("--output", default="", help="Optional txt output path. If omitted, only print URLs.")
    parser.add_argument("--browser-wait", default=8, type=int, help="Seconds to wait for Douyin pages to render.")
    parser.add_argument("--show-browser", action="store_true", help="Show browser window while collecting Douyin pages.")
    parser.add_argument("--use-edge-profile", action="store_true", help="Reuse the local Edge signed-in profile instead of importing cookies.")
    parser.add_argument("--edge-profile-dir", default="Default", help="Edge profile directory name when using --use-edge-profile, for example Default or Profile 1.")
    args = parser.parse_args()

    page_url, inferred_platform = resolve_creator_input(
        creator_url=args.creator_url,
        creator_id=args.creator_id,
        platform=args.platform,
        proxy=args.proxy,
        browser_cookies=args.cookies_from_browser,
    )
    platform = inferred_platform or args.platform

    urls, inferred_creator_name = collect_urls(
        page_url=page_url,
        platform=platform,
        count=args.count,
        proxy=args.proxy,
        browser_cookies=args.cookies_from_browser,
        browser_wait=args.browser_wait,
        headless=not args.show_browser,
        use_edge_profile=args.use_edge_profile,
        edge_profile_dir=args.edge_profile_dir,
    )
    fallback_name = page_url.rsplit("/", 1)[-1]
    creator_name = args.creator_name.strip() or inferred_creator_name or sanitize_filename(fallback_name, max_len=80)

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(urls) + "\n", encoding="utf-8")
        print(f"Creator: {creator_name}")
        print(f"URLs: {len(urls)}")
        print(f"Output: {output_path}")
    else:
        for url in urls:
            print(url)

    return 0


if __name__ == "__main__":
    sys.exit(main())
