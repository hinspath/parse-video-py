import asyncio
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx


_log = logging.getLogger(__name__)
_browser_slot = asyncio.Lock()
_FRAME_PREFIX = "self.__pace_f.push("
_DEFAULT_SOCKET = "/run/douyin-live/browser.sock"
# The same work may use douyinvod locally and zjcdn on the production host.
_CDN_SUFFIXES = (".douyinvod.com", ".zjcdn.com")
_BROWSER_TIMEOUT = 12.0


def _live_src(video: dict) -> str:
    addresses = video.get("playAddr")
    if not isinstance(addresses, list):
        return ""
    for address in addresses:
        src = address.get("src") if isinstance(address, dict) else None
        if not isinstance(src, str):
            continue
        try:
            url = urlsplit(src)
            if (
                url.scheme == "https"
                and (url.hostname or "").endswith(_CDN_SUFFIXES)
                and not url.username
                and not url.password
                and url.port in (None, 443)
            ):
                return src
        except ValueError:
            continue
    return ""


def _live_urls_from_frames(scripts: list[str], work_id: str) -> dict[str, str]:
    # The public desktop page serializes its work into hydration frames:
    # push([1, '<record id>:<JSON>']). Decode both layers without running JS
    # from the frame, and require the frame's work ID before reading images.
    decoder = json.JSONDecoder()
    for script in scripts:
        if not script.startswith(_FRAME_PREFIX) or work_id not in script:
            continue
        try:
            frame, _ = decoder.raw_decode(script[len(_FRAME_PREFIX):].lstrip())
        except ValueError:
            continue
        if not isinstance(frame, list) or len(frame) < 2 or not isinstance(frame[1], str):
            continue
        for line in frame[1].splitlines():
            _, sep, body = line.partition(":")
            if not sep or work_id not in body or '"clipType"' not in body:
                continue
            try:
                node = json.loads(body)
            except ValueError:
                continue
            if (
                not isinstance(node, list)
                or len(node) < 4
                or not isinstance(node[3], dict)
                or node[3].get("awemeId") != work_id
            ):
                continue
            props = node[3]
            aweme = props.get("aweme")
            if not isinstance(aweme, dict) or aweme.get("statusCode") != 0:
                continue
            detail = aweme.get("detail")
            rows = detail.get("images") if isinstance(detail, dict) else None
            if not isinstance(rows, list):
                continue

            urls = {}
            seen = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                uri = row.get("uri")
                if not isinstance(uri, str) or not uri:
                    continue
                # A repeated URI is ambiguous; don't guess which clip belongs to it.
                if uri in seen:
                    urls.pop(uri, None)
                    continue
                seen.add(uri)
                video = row.get("video")
                # Observed desktop types: 2 = static, 3 and 5 = Live.
                # The public share API does not consistently use these types.
                if row.get("clipType") in (3, 5) and isinstance(video, dict):
                    src = _live_src(video)
                    if src:
                        urls[uri] = src
            return urls
    return {}


async def get_desktop_live_urls(work_id: str) -> dict[str, str]:
    if not _valid_work_id(work_id):
        return {}
    # Production runs the API as root. The private socket keeps Chromium
    # sandboxed in a separate unprivileged service without account cookies.
    socket_path = os.getenv("DOUYIN_LIVE_SOCKET", _DEFAULT_SOCKET)
    if os.name == "posix" and socket_path and Path(socket_path).is_socket():
        try:
            transport = httpx.AsyncHTTPTransport(uds=socket_path, trust_env=False)
            async with httpx.AsyncClient(
                transport=transport, timeout=_BROWSER_TIMEOUT + 2
            ) as client:
                response = await client.get(f"http://douyin-live/live/{work_id}")
                response.raise_for_status()
                urls = response.json()
                return urls if isinstance(urls, dict) else {}
        except (httpx.HTTPError, ValueError) as err:
            _log.info("Douyin desktop Live worker unavailable: %s", type(err).__name__)
            return {}
    return await read_desktop_live_urls(work_id)


def _valid_work_id(work_id: str) -> bool:
    return 1 <= len(work_id) <= 22 and work_id.isascii() and work_id.isdecimal()


async def read_desktop_live_urls(work_id: str) -> dict[str, str]:
    # If the optional backend is unavailable, return the images already
    # parsed. Never queue additional browsers or disable Chromium's sandbox.
    if not _valid_work_id(work_id) or _browser_slot.locked():
        return {}
    if getattr(os, "geteuid", lambda: -1)() == 0:
        return {}
    try:
        from playwright.async_api import Error as BrowserError
        from playwright.async_api import async_playwright
    except ImportError:
        return {}

    async def read_page() -> dict[str, str]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(chromium_sandbox=True)
            try:
                page = await browser.new_page()

                async def skip_assets(route):
                    # Reading hydration metadata needs neither images nor clips.
                    if route.request.resource_type in {"image", "media", "font"}:
                        await route.abort()
                    else:
                        await route.continue_()

                await page.route("**/*", skip_assets)
                response = await page.goto(
                    f"https://www.douyin.com/note/{work_id}",
                    # Slow page assets must not delay reading inline frames.
                    wait_until="commit",
                    timeout=7000,
                )
                if not response or not response.ok:
                    return {}
                frames = await page.wait_for_function(
                    """workId => {
                        const frames = Array.from(document.scripts, s => s.textContent)
                            .filter(s => s && s.startsWith("self.__pace_f.push(")
                                && s.length < 4_000_000 && s.includes("clipType")
                                && s.includes(workId));
                        return frames.length ? frames : null;
                    }""",
                    arg=work_id,
                )
                if urlsplit(page.url).hostname != "www.douyin.com":
                    return {}
                return _live_urls_from_frames(await frames.json_value(), work_id)
            finally:
                await browser.close()

    async with _browser_slot:
        try:
            urls = await asyncio.wait_for(read_page(), timeout=_BROWSER_TIMEOUT)
        except (asyncio.TimeoutError, BrowserError, OSError) as err:
            _log.info("Douyin desktop Live fallback unavailable: %s", type(err).__name__)
            return {}
    _log.info("Douyin desktop Live fallback: work=%s clips=%d", work_id, len(urls))
    return urls
