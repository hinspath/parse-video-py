import base64
import dataclasses
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi_mcp import FastApiMCP
from pydantic import BaseModel

from parse_video_py import VideoSource, parse_video_id, parse_video_share_url
from parse_video_py.parser.douyin import DouYin
from parse_video_py.utils import extract_url


def _get_templates_dir() -> str:
    # 模板已移入 src/parse_video_py/templates/，与 web.py 同级
    templates_dir = Path(__file__).parent / "templates"
    if templates_dir.is_dir():
        return str(templates_dir)
    raise FileNotFoundError("templates 目录未找到")


app = FastAPI()

mcp = FastApiMCP(app)
mcp.mount_http()

templates = Jinja2Templates(directory=_get_templates_dir())

API_SECRET_TOKEN = os.getenv("API_SECRET_TOKEN", "wxd8f9c2a1b3_my_secret_pwd")
MINIPROGRAM_API_KEY = os.getenv(
    "MINIPROGRAM_API_KEY", "HinsCheung_Love_Video_Parser_2026_No_Copy"
)
DOUYIN_COOKIE_UPDATE_PASSWORD = os.getenv(
    "DOUYIN_COOKIE_UPDATE_PASSWORD", "WhatFuck.1"
)
ERROR_REPORT_FILE = Path(
    os.getenv(
        "ERROR_REPORT_FILE",
        str(Path.cwd() / "public" / "uploads" / "error_domains.json"),
    )
)
DOUYIN_COOKIE_FILE = Path(
    os.getenv(
        "DOUYIN_COOKIE_FILE",
        str(Path.cwd() / ".runtime" / "douyin_cookie.txt"),
    )
)
DOWNLOAD_PROXY_MODE_FILE = Path(
    os.getenv(
        "DOWNLOAD_PROXY_MODE_FILE",
        str(Path.cwd() / ".runtime" / "download_proxy_mode.json"),
    )
)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
DOWNLOAD_PROXY_SECRET = os.getenv("DOWNLOAD_PROXY_SECRET", API_SECRET_TOKEN)
DOWNLOAD_PROXY_TTL_SECONDS = int(os.getenv("DOWNLOAD_PROXY_TTL_SECONDS", "1800"))
DOWNLOAD_PROXY_ENABLED_DEFAULT = os.getenv("DOWNLOAD_PROXY_ENABLED", "true")
AUTH_WHITELIST = {
    "/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
    "/favicon.png",
    "/api/download",
    "/api/download_proxy_mode",
    "/api/get_errors",
    "/api/update_cookie",
}
AUTH_WHITELIST_PREFIXES = ("/docs/", "/static/")


class CookieUpdateParams(BaseModel):
    password: str
    cookie: str


class ErrorDomainParams(BaseModel):
    domain: str


class DownloadProxyModeParams(BaseModel):
    enabled: bool
    password: str = ""


def _request_is_authorized(request: Request) -> bool:
    tokens = {
        value
        for value in (API_SECRET_TOKEN, MINIPROGRAM_API_KEY)
        if value
    }
    return (
        request.headers.get("x-auth-token") in tokens
        or request.headers.get("x-api-key") in tokens
    )


def _add_compat_fields(data: dict) -> dict:
    if data.get("video_url") and not data.get("url"):
        data["url"] = data["video_url"]
    if data.get("cover_url") and not data.get("cover"):
        data["cover"] = data["cover_url"]
    if data.get("video_urls") and not data.get("qualities"):
        data["qualities"] = data["video_urls"]

    for image in data.get("images") or []:
        if not isinstance(image, dict):
            continue
        if image.get("url") and not image.get("local_url"):
            image["local_url"] = image["url"]
        if image.get("live_photo_url") and not image.get("local_live_photo_url"):
            image["local_live_photo_url"] = image["live_photo_url"]

    return data


def _success_payload(video_info, request: Request | None = None):
    data = _add_compat_fields(dataclasses.asdict(video_info))
    _add_download_proxy_fields(data, request)
    return {
        "code": 200,
        "msg": "解析成功",
        "data": data,
    }


async def _parse_share_url_payload(url: str, request: Request | None = None):
    video_share_url = extract_url(url)
    if video_share_url is None:
        return {
            "code": 400,
            "msg": "未检测到有效的分享链接",
        }

    try:
        video_info = await parse_video_share_url(video_share_url)
        return _success_payload(video_info, request)
    except Exception as err:
        return {
            "code": 500,
            "msg": str(err),
        }


def _read_error_domains() -> list[str]:
    try:
        if not ERROR_REPORT_FILE.exists():
            return []
        raw = json.loads(ERROR_REPORT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(raw, list):
        return []

    domains = []
    for item in raw:
        if isinstance(item, str):
            domain = _normalize_domain(item)
        elif isinstance(item, dict):
            domain = _normalize_domain(str(item.get("domain") or ""))
        else:
            domain = ""
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def _write_error_domains(domains: list[str]) -> None:
    ERROR_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ERROR_REPORT_FILE.write_text(
        json.dumps(domains, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_persisted_douyin_cookie() -> str:
    try:
        if DOUYIN_COOKIE_FILE.exists():
            return DOUYIN_COOKIE_FILE.read_text(encoding="utf-8").strip()
    except Exception as err:
        print(f"[DouYin] read persisted cookie failed: {err}")
    return ""


def _write_persisted_douyin_cookie(cookie: str) -> None:
    DOUYIN_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DOUYIN_COOKIE_FILE.write_text(cookie.strip(), encoding="utf-8")
    try:
        os.chmod(DOUYIN_COOKIE_FILE, 0o600)
    except Exception:
        pass


def _parse_bool(value: str, default: bool = True) -> bool:
    if value is None:
        return default

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enable", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disable", "disabled"}:
        return False
    return default


def _read_download_proxy_enabled() -> bool:
    try:
        if DOWNLOAD_PROXY_MODE_FILE.exists():
            raw = json.loads(DOWNLOAD_PROXY_MODE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "enabled" in raw:
                return bool(raw["enabled"])
    except Exception as err:
        print(f"[DownloadProxy] read mode failed: {err}")

    return _parse_bool(DOWNLOAD_PROXY_ENABLED_DEFAULT, True)


def _write_download_proxy_enabled(enabled: bool) -> None:
    DOWNLOAD_PROXY_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_PROXY_MODE_FILE.write_text(
        json.dumps(
            {"enabled": bool(enabled), "updated_at": int(time.time())},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    try:
        os.chmod(DOWNLOAD_PROXY_MODE_FILE, 0o600)
    except Exception:
        pass


def _bootstrap_persisted_douyin_cookie() -> None:
    cookie = _read_persisted_douyin_cookie()
    if cookie:
        DouYin.update_cookie(cookie)


def _normalize_domain(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    if "://" in text:
        parsed = urlparse(text)
        text = parsed.netloc or parsed.path
    else:
        text = text.split("/", 1)[0]

    return text.split("?", 1)[0].strip().lower()


def _get_public_base_url(request: Request | None) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    if request is None:
        return ""

    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def _encode_download_url(url: str) -> str:
    return base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_download_url(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8")


def _sign_download_url(encoded_url: str, expires: int) -> str:
    payload = f"{encoded_url}.{expires}".encode("utf-8")
    secret = DOWNLOAD_PROXY_SECRET.encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _build_download_proxy_url(url: str, request: Request | None) -> str:
    if not url:
        return ""

    base_url = _get_public_base_url(request)
    if not base_url:
        return ""

    encoded_url = _encode_download_url(url)
    expires = int(time.time()) + DOWNLOAD_PROXY_TTL_SECONDS
    signature = _sign_download_url(encoded_url, expires)
    return f"{base_url}/api/download?u={encoded_url}&e={expires}&s={signature}"


def _verify_download_proxy_params(encoded_url: str, expires: int, signature: str) -> str:
    if expires < int(time.time()):
        raise ValueError("download url expired")

    expected_signature = _sign_download_url(encoded_url, expires)
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("invalid download signature")

    url = _decode_download_url(encoded_url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("invalid download url")

    hostname = (parsed.hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("invalid download host")

    return url


def _add_download_proxy_fields(data: dict, request: Request | None) -> None:
    data["download_proxy_enabled"] = _read_download_proxy_enabled()
    if not data["download_proxy_enabled"]:
        return

    if request is None:
        return

    if data.get("video_url"):
        data["download_url"] = _build_download_proxy_url(data["video_url"], request)
    if data.get("cover_url"):
        data["cover_download_url"] = _build_download_proxy_url(
            data["cover_url"],
            request,
        )
    if data.get("music_url"):
        data["music_download_url"] = _build_download_proxy_url(
            data["music_url"],
            request,
        )

    for video in data.get("video_urls") or []:
        if isinstance(video, dict) and video.get("url"):
            video["download_url"] = _build_download_proxy_url(video["url"], request)

    for image in data.get("images") or []:
        if not isinstance(image, dict):
            continue
        if image.get("url"):
            image["download_url"] = _build_download_proxy_url(image["url"], request)
        if image.get("live_photo_url"):
            image["live_photo_download_url"] = _build_download_proxy_url(
                image["live_photo_url"],
                request,
            )


async def _resolve_redirect_url(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Range": "bytes=0-0",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            response = await client.get(url, headers=headers)
            return str(response.url)
    except Exception:
        return url


_bootstrap_persisted_douyin_cookie()


@app.middleware("http")
async def verify_secret_header(request: Request, call_next):
    path = request.url.path
    if path in AUTH_WHITELIST or path.startswith(AUTH_WHITELIST_PREFIXES):
        return await call_next(request)

    if not _request_is_authorized(request):
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "鉴权失败：请在 Header 中提供正确的 x-auth-token"},
        )

    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "Video Parser",
        },
    )


@app.post("/api/update_cookie")
async def update_cookie_api(params: CookieUpdateParams):
    if params.password != DOUYIN_COOKIE_UPDATE_PASSWORD:
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "管理密码错误"},
        )

    if not params.cookie.strip():
        return JSONResponse(
            status_code=400,
            content={"code": 400, "msg": "Cookie 不能为空"},
        )

    try:
        _write_persisted_douyin_cookie(params.cookie)
    except Exception as err:
        return JSONResponse(
            status_code=500,
            content={"code": 500, "msg": f"Cookie 保存失败：{err}"},
        )

    DouYin.update_cookie(params.cookie)
    return {"code": 200, "msg": "Cookie 更新成功，已保存，重启后仍生效"}


@app.get("/api/download_proxy_mode")
async def get_download_proxy_mode_api():
    return {
        "code": 200,
        "msg": "ok",
        "data": {"enabled": _read_download_proxy_enabled()},
    }


@app.post("/api/download_proxy_mode")
async def update_download_proxy_mode_api(request: Request, params: DownloadProxyModeParams):
    if not _request_is_authorized(request) and params.password != DOUYIN_COOKIE_UPDATE_PASSWORD:
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "auth failed"},
        )

    _write_download_proxy_enabled(params.enabled)
    return {
        "code": 200,
        "msg": "download proxy mode updated",
        "data": {"enabled": params.enabled},
    }


@app.get("/video/share/url/parse")
async def share_url_parse(request: Request, url: str):
    return await _parse_share_url_payload(url, request)


@app.get("/api/parse")
@app.get("/api/analysis")
async def legacy_parse_api(request: Request, url: str):
    return await _parse_share_url_payload(url, request)


@app.get("/api/resolve_redirect")
async def legacy_resolve_redirect_api(url: str):
    if not url:
        return {"code": 400, "msg": "missing url", "url": ""}
    return {"code": 200, "url": await _resolve_redirect_url(url)}


@app.get("/api/download")
async def proxy_download_api(request: Request, u: str, e: int, s: str):
    if not _read_download_proxy_enabled():
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "download proxy disabled"},
        )

    try:
        target_url = _verify_download_proxy_params(u, e, s)
    except Exception as err:
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": str(err)},
        )

    request_headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Referer": "https://www.douyin.com/",
    }
    # WeChat downloadFile can retry partial proxy responses repeatedly. Always
    # fetch and return one full object so the client sees a normal 200 stream.

    client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, read=None),
    )
    try:
        upstream = await client.send(
            client.build_request("GET", target_url, headers=request_headers),
            stream=True,
        )
    except Exception as err:
        await client.aclose()
        return JSONResponse(
            status_code=502,
            content={"code": 502, "msg": f"download upstream failed: {err}"},
        )

    if upstream.status_code >= 400:
        status_code = upstream.status_code
        await upstream.aclose()
        await client.aclose()
        return JSONResponse(
            status_code=status_code,
            content={"code": status_code, "msg": "download upstream rejected"},
        )

    response_headers = {}
    for header in (
        "content-length",
        "cache-control",
    ):
        if upstream.headers.get(header):
            response_headers[header] = upstream.headers[header]
    response_headers["Content-Disposition"] = 'attachment; filename="download"'
    response_headers["Accept-Ranges"] = "none"

    media_type = upstream.headers.get("content-type") or "application/octet-stream"
    status_code = 200 if upstream.status_code == 206 else upstream.status_code

    async def stream_body():
        try:
            async for chunk in upstream.aiter_bytes(1024 * 256):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_body(),
        status_code=status_code,
        headers=response_headers,
        media_type=media_type,
    )


@app.get("/api/get_errors")
async def legacy_get_errors_api():
    return _read_error_domains()


@app.post("/api/report_error")
async def legacy_report_error_api(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    domain = _normalize_domain(
        str(
            payload.get("domain")
            or payload.get("url")
            or request.query_params.get("domain")
            or ""
        )
    )
    if not domain:
        return {"code": 400, "msg": "missing domain"}

    domains = _read_error_domains()
    if domain not in domains:
        domains.append(domain)
        _write_error_domains(domains)

    return {"code": 200, "msg": "ok"}


@app.post("/api/delete_error")
async def legacy_delete_error_api(params: ErrorDomainParams):
    domain = _normalize_domain(params.domain)
    if not domain:
        return {"code": 400, "msg": "missing domain"}

    domains = _read_error_domains()
    updated_domains = [item for item in domains if item != domain]
    _write_error_domains(updated_domains)
    return {"code": 200, "msg": "ok", "data": updated_domains}


@app.post("/api/clear_errors")
async def legacy_clear_errors_api():
    _write_error_domains([])
    return {"code": 200, "msg": "ok", "data": []}


@app.get("/video/id/parse")
async def video_id_parse(request: Request, source: VideoSource, video_id: str):
    try:
        video_info = await parse_video_id(source, video_id)
        return _success_payload(video_info, request)
    except Exception as err:
        return {
            "code": 500,
            "msg": str(err),
        }


mcp.setup_server()
