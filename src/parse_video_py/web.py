import asyncio
import base64
import dataclasses
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

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
MINIPROGRAM_AUTH_MODE = os.getenv("MINIPROGRAM_AUTH_MODE", "api_key").lower()
WECHAT_MINIPROGRAM_APPID = os.getenv("WECHAT_MINIPROGRAM_APPID", "")
WECHAT_MINIPROGRAM_SECRET = os.getenv("WECHAT_MINIPROGRAM_SECRET", "")
WECHAT_SESSION_SECRET = os.getenv("WECHAT_SESSION_SECRET", API_SECRET_TOKEN)
WECHAT_SESSION_TTL_SECONDS = int(os.getenv("WECHAT_SESSION_TTL_SECONDS", "86400"))
DOUYIN_COOKIE_UPDATE_PASSWORD = os.getenv(
    "DOUYIN_COOKIE_UPDATE_PASSWORD", "WhatFuck.1"
)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "hinspath@gmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", DOUYIN_COOKIE_UPDATE_PASSWORD)
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
PLATFORM_COOKIE_FILE = Path(
    os.getenv(
        "PLATFORM_COOKIE_FILE",
        str(Path.cwd() / ".runtime" / "platform_cookies.json"),
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
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
AUTH_WHITELIST = {
    "/",
    "/admin",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
    "/favicon.png",
    "/api/download",
    "/api/download_proxy_mode",
    "/api/get_errors",
    "/api/resolve_redirect",
    "/api/wx/login",
    "/api/update_cookie",
    "/api/platform_cookies",
    "/api/platform_cookies/status",
    "/api/delete_error",
    "/api/clear_errors",
    "/video/share/url/parse",
}
AUTH_WHITELIST_PREFIXES = ("/docs/", "/static/")


class CookieUpdateParams(BaseModel):
    password: str
    cookie: str


class PlatformCookieUpdateParams(BaseModel):
    password: str
    cookies: dict[str, str] = {}


class ErrorDomainParams(BaseModel):
    domain: str
    password: str = ""


class DownloadProxyModeParams(BaseModel):
    enabled: bool
    password: str = ""


class AdminPasswordParams(BaseModel):
    password: str = ""


class WechatLoginParams(BaseModel):
    code: str


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


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _create_wechat_session_token(openid: str) -> tuple[str, int]:
    expires_at = int(time.time()) + WECHAT_SESSION_TTL_SECONDS
    payload = {
        "openid": openid,
        "exp": expires_at,
    }
    payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    encoded_payload = _b64url_encode(payload_text.encode("utf-8"))
    signature = hmac.new(
        WECHAT_SESSION_SECRET.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded_payload}.{signature}", expires_at


def _verify_wechat_session_token(token: str) -> dict:
    if not token or "." not in token:
        raise ValueError("missing wechat session")

    encoded_payload, signature = token.rsplit(".", 1)
    expected_signature = hmac.new(
        WECHAT_SESSION_SECRET.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("invalid wechat session")

    payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
    if int(payload.get("exp") or 0) < int(time.time()):
        raise ValueError("wechat session expired")
    if not payload.get("openid"):
        raise ValueError("invalid wechat session payload")
    return payload


def _request_has_wechat_session(request: Request) -> bool:
    token = (request.headers.get("x-wx-session") or "").strip()
    try:
        _verify_wechat_session_token(token)
        return True
    except Exception:
        return False


async def _request_has_valid_turnstile(request: Request) -> bool:
    if not TURNSTILE_SECRET_KEY:
        return True

    token = (
        request.headers.get("x-turnstile-token")
        or request.query_params.get("turnstile_token")
        or ""
    ).strip()
    if not token:
        return False

    remote_ip = request.client.host if request.client else ""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={
                    "secret": TURNSTILE_SECRET_KEY,
                    "response": token,
                    "remoteip": remote_ip,
                },
            )
        payload = response.json()
        return bool(payload.get("success"))
    except Exception:
        return False


def _miniprogram_requires_wechat_session() -> bool:
    return MINIPROGRAM_AUTH_MODE in {"wechat", "wx", "openid"}


def _miniprogram_request_is_authorized(request: Request) -> bool:
    if _miniprogram_requires_wechat_session():
        return _request_has_wechat_session(request)
    return _request_is_authorized(request)


async def _wechat_code_to_openid(code: str) -> str:
    if not WECHAT_MINIPROGRAM_APPID or not WECHAT_MINIPROGRAM_SECRET:
        raise RuntimeError("wechat appid/secret not configured")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": WECHAT_MINIPROGRAM_APPID,
                "secret": WECHAT_MINIPROGRAM_SECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            },
        )
    payload = response.json()
    if payload.get("errcode"):
        raise RuntimeError(payload.get("errmsg") or "wechat login failed")
    openid = payload.get("openid")
    if not openid:
        raise RuntimeError("wechat login did not return openid")
    return str(openid)


def _admin_password_is_valid(password: str) -> bool:
    if not password:
        return False
    return hmac.compare_digest(password, DOUYIN_COOKIE_UPDATE_PASSWORD)


def _admin_basic_auth_is_valid(request: Request) -> bool:
    auth_header = (request.headers.get("authorization") or "").strip()
    if not auth_header.lower().startswith("basic "):
        return False

    try:
        decoded = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return False

    username, separator, password = decoded.partition(":")
    if not separator:
        return False

    return hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(
        password,
        ADMIN_PASSWORD,
    )


def _admin_request_is_authorized(request: Request, password: str = "") -> bool:
    return _admin_basic_auth_is_valid(request) or _admin_password_is_valid(password)


def _admin_basic_auth_response() -> HTMLResponse:
    return HTMLResponse(
        status_code=401,
        content="<h1>401 Authorization Required</h1>",
        headers={"WWW-Authenticate": 'Basic realm="Video Parser Admin", charset="UTF-8"'},
    )


def _supported_cookie_platforms() -> tuple[str, ...]:
    return ("redbook", "douyin", "kuaishou", "bilibili", "weibo")


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

    request_cookie_token = None
    if request is not None:
        request_cookie = (request.headers.get("x-douyin-cookie") or "").strip()
        if request_cookie:
            request_cookie_token = DouYin.set_request_cookie(request_cookie)

    try:
        video_info = await parse_video_share_url(video_share_url)
        return _success_payload(video_info, request)
    except Exception as err:
        return {
            "code": 500,
            "msg": str(err),
        }
    finally:
        if request_cookie_token is not None:
            DouYin.reset_request_cookie(request_cookie_token)


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


def _read_platform_cookies() -> dict[str, str]:
    cookies = {platform: "" for platform in _supported_cookie_platforms()}
    try:
        if PLATFORM_COOKIE_FILE.exists():
            raw = json.loads(PLATFORM_COOKIE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for platform in _supported_cookie_platforms():
                    value = raw.get(platform)
                    if isinstance(value, str):
                        cookies[platform] = value.strip()
    except Exception as err:
        print(f"[Cookie] read platform cookies failed: {err}")

    legacy_douyin_cookie = _read_persisted_douyin_cookie()
    if legacy_douyin_cookie and not cookies["douyin"]:
        cookies["douyin"] = legacy_douyin_cookie

    return cookies


def _write_platform_cookies(cookies: dict[str, str]) -> dict[str, str]:
    normalized = {
        platform: str(cookies.get(platform) or "").strip()
        for platform in _supported_cookie_platforms()
    }
    PLATFORM_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLATFORM_COOKIE_FILE.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        os.chmod(PLATFORM_COOKIE_FILE, 0o600)
    except Exception:
        pass

    _write_persisted_douyin_cookie(normalized["douyin"])
    DouYin.update_cookie(normalized["douyin"])
    return normalized


def _platform_cookie_status() -> dict[str, bool]:
    cookies = _read_platform_cookies()
    return {platform: bool(cookies.get(platform)) for platform in _supported_cookie_platforms()}


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
    cookie = _read_platform_cookies().get("douyin", "")
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


def _download_request_headers(target_url: str) -> dict:
    parsed = urlparse(target_url)
    host = parsed.netloc.lower()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    if "kwimgs.com" in host or "kuaishou.com" in host:
        headers["Referer"] = "https://v.kuaishou.com/"
    elif "douyin.com" in host or "douyinvod.com" in host or "zjcdn.com" in host:
        headers["Referer"] = "https://www.douyin.com/"
    elif parsed.scheme and parsed.netloc:
        headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"

    return headers


async def _open_upstream_download(
    client: httpx.AsyncClient,
    target_url: str,
    request_headers: dict,
    start: int = 0,
    force_range: bool = False,
) -> httpx.Response:
    headers = dict(request_headers)
    if force_range or start > 0:
        headers["Range"] = f"bytes={start}-"

    return await client.send(
        client.build_request("GET", target_url, headers=headers),
        stream=True,
    )


def _parse_content_range_total(value: str | None) -> int:
    if not value:
        return 0
    try:
        total_text = value.rsplit("/", 1)[-1]
        if total_text and total_text != "*":
            return int(total_text)
    except Exception:
        return 0
    return 0


def _parse_range_start(value: str | None) -> int:
    if not value:
        return 0
    text = value.strip().lower()
    if not text.startswith("bytes="):
        return 0
    start_text = text[6:].split(",", 1)[0].split("-", 1)[0].strip()
    if not start_text:
        return 0
    try:
        return max(0, int(start_text))
    except Exception:
        return 0


def _get_upstream_total_size(upstream: httpx.Response) -> int:
    content_range_total = _parse_content_range_total(
        upstream.headers.get("content-range")
    )
    if content_range_total:
        return content_range_total

    try:
        return int(upstream.headers.get("content-length") or 0)
    except Exception:
        return 0


def _guess_download_extension(url: str, media_type: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path or "").lower()
    known_exts = (
        ".mp4",
        ".mov",
        ".m4v",
        ".webm",
        ".mp3",
        ".m4a",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
    )
    for ext in known_exts:
        if path.endswith(ext):
            return ext.lstrip(".")

    content_type = (media_type or "").split(";", 1)[0].lower()
    if content_type == "video/mp4":
        return "mp4"
    if content_type == "video/quicktime":
        return "mov"
    if content_type == "video/webm":
        return "webm"
    if content_type in {"audio/mpeg", "audio/mp3"}:
        return "mp3"
    if content_type in {"audio/mp4", "audio/x-m4a"}:
        return "m4a"
    if content_type == "image/png":
        return "png"
    if content_type == "image/webp":
        return "webp"
    if content_type == "image/gif":
        return "gif"
    if content_type in {"image/jpeg", "image/jpg"}:
        return "jpg"
    if content_type.startswith("video/"):
        return "mp4"
    if content_type.startswith("audio/"):
        return "mp3"
    if content_type.startswith("image/"):
        return "jpg"
    return "bin"


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

    if not (_request_is_authorized(request) or _request_has_wechat_session(request)):
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
            "turnstile_site_key": TURNSTILE_SITE_KEY,
        },
    )


@app.get("/admin", response_class=HTMLResponse)
async def read_admin(request: Request):
    if not _admin_basic_auth_is_valid(request):
        return _admin_basic_auth_response()

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "title": "Video Parser Admin",
        },
    )


@app.post("/api/update_cookie")
async def update_cookie_api(request: Request, params: CookieUpdateParams):
    if not _admin_request_is_authorized(request, params.password):
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


@app.get("/api/platform_cookies/status")
async def get_platform_cookies_status_api(request: Request):
    if not _request_is_authorized(request) and not _admin_basic_auth_is_valid(request):
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Video Parser Admin"'},
            content={"code": 401, "msg": "auth required"},
        )

    return {"code": 200, "msg": "ok", "data": _platform_cookie_status()}


@app.post("/api/platform_cookies")
async def update_platform_cookies_api(request: Request, params: PlatformCookieUpdateParams):
    if not _admin_request_is_authorized(request, params.password):
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "管理密码错误"},
        )

    existing = _read_platform_cookies()
    for platform in _supported_cookie_platforms():
        if platform in params.cookies:
            existing[platform] = str(params.cookies.get(platform) or "").strip()

    saved = _write_platform_cookies(existing)
    return {
        "code": 200,
        "msg": "平台 Cookie 已保存",
        "data": {platform: bool(saved.get(platform)) for platform in _supported_cookie_platforms()},
    }


@app.get("/api/download_proxy_mode")
async def get_download_proxy_mode_api():
    return {
        "code": 200,
        "msg": "ok",
        "data": {"enabled": _read_download_proxy_enabled()},
    }


@app.post("/api/wx/login")
async def wechat_login_api(params: WechatLoginParams):
    try:
        openid = await _wechat_code_to_openid(params.code.strip())
        token, expires_at = _create_wechat_session_token(openid)
        return {
            "code": 200,
            "msg": "ok",
            "data": {
                "token": token,
                "expires_at": expires_at,
            },
        }
    except Exception as err:
        return JSONResponse(
            status_code=401,
            content={"code": 401, "msg": str(err)},
        )


@app.post("/api/download_proxy_mode")
async def update_download_proxy_mode_api(request: Request, params: DownloadProxyModeParams):
    if not _request_is_authorized(request) and not _admin_request_is_authorized(
        request,
        params.password,
    ):
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
    if not await _request_has_valid_turnstile(request):
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "验证码校验失败，请刷新页面后重试"},
        )
    return await _parse_share_url_payload(url, request)


@app.get("/api/parse")
@app.get("/api/analysis")
async def legacy_parse_api(request: Request, url: str):
    if not _miniprogram_request_is_authorized(request):
        return JSONResponse(
            status_code=401,
            content={"code": 401, "msg": "微信登录态无效，请重新进入小程序"},
        )
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

    request_headers = _download_request_headers(target_url)
    range_header = request.headers.get("range")
    range_requested = bool(
        range_header and range_header.strip().lower().startswith("bytes=")
    )
    range_start = _parse_range_start(range_header)
    # WeChat downloadFile expects a stable 200 stream. Some upstream video CDNs
    # drop long connections mid-file, so the proxy retries upstream with Range
    # and keeps one continuous response open for the client.

    client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, read=None),
    )
    try:
        upstream = await _open_upstream_download(
            client,
            target_url,
            request_headers,
            range_start,
            range_requested,
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

    total_size = _get_upstream_total_size(upstream)
    response_headers = {}
    for header in (
        "cache-control",
    ):
        if upstream.headers.get(header):
            response_headers[header] = upstream.headers[header]
    media_type = upstream.headers.get("content-type") or "application/octet-stream"
    extension = _guess_download_extension(target_url, media_type)
    filename = f"download.{extension}"
    range_response = range_requested and upstream.status_code == 206 and total_size
    if range_response:
        response_headers["content-length"] = str(max(0, total_size - range_start))
        response_headers["Content-Range"] = f"bytes {range_start}-{total_size - 1}/{total_size}"
    elif total_size:
        response_headers["content-length"] = str(total_size)
    disposition = "inline" if range_requested else "attachment"
    response_headers["Content-Disposition"] = (
        f'{disposition}; filename="{filename}"; filename*=UTF-8\'\'{filename}'
    )
    response_headers["Accept-Ranges"] = "bytes"
    status_code = (
        206
        if range_response
        else (200 if upstream.status_code == 206 else upstream.status_code)
    )

    async def stream_body():
        nonlocal upstream
        sent = range_start if range_response else 0
        retry_count = 0
        max_retries = 8
        try:
            while True:
                try:
                    async for chunk in upstream.aiter_bytes(1024 * 512):
                        if not chunk:
                            continue
                        sent += len(chunk)
                        yield chunk
                except Exception as err:
                    print(
                        "[DownloadProxy] upstream interrupted "
                        f"sent={sent} total={total_size}: {err}"
                    )

                if not total_size or sent >= total_size:
                    break

                retry_count += 1
                if retry_count > max_retries:
                    print(
                        "[DownloadProxy] upstream retry limit reached "
                        f"sent={sent} total={total_size}"
                    )
                    break

                try:
                    await upstream.aclose()
                except Exception:
                    pass

                resumed = False
                while retry_count <= max_retries:
                    try:
                        upstream = await _open_upstream_download(
                            client,
                            target_url,
                            request_headers,
                            sent,
                        )
                        if upstream.status_code != 206:
                            print(
                                "[DownloadProxy] upstream did not honor range "
                                f"status={upstream.status_code} sent={sent}"
                            )
                            break
                        print(
                            "[DownloadProxy] resumed upstream "
                            f"from={sent} total={total_size} retry={retry_count}"
                        )
                        resumed = True
                        break
                    except Exception as err:
                        print(
                            "[DownloadProxy] upstream resume failed "
                            f"from={sent} total={total_size}: {err}"
                        )
                        retry_count += 1
                        await asyncio.sleep(min(retry_count, 3))

                if not resumed:
                    break
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
async def legacy_delete_error_api(request: Request, params: ErrorDomainParams):
    if not _request_is_authorized(request) and not _admin_request_is_authorized(
        request,
        params.password,
    ):
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "auth failed"},
        )

    domain = _normalize_domain(params.domain)
    if not domain:
        return {"code": 400, "msg": "missing domain"}

    domains = _read_error_domains()
    updated_domains = [item for item in domains if item != domain]
    _write_error_domains(updated_domains)
    return {"code": 200, "msg": "ok", "data": updated_domains}


@app.post("/api/clear_errors")
async def legacy_clear_errors_api(request: Request, params: AdminPasswordParams):
    if not _request_is_authorized(request) and not _admin_request_is_authorized(
        request,
        params.password,
    ):
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "auth failed"},
        )

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
