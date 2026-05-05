import dataclasses
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
DOUYIN_COOKIE_UPDATE_PASSWORD = os.getenv(
    "DOUYIN_COOKIE_UPDATE_PASSWORD", "WhatFuck.1"
)
AUTH_WHITELIST = {
    "/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
    "/api/update_cookie",
}
AUTH_WHITELIST_PREFIXES = ("/docs/", "/static/")


class CookieUpdateParams(BaseModel):
    password: str
    cookie: str


@app.middleware("http")
async def verify_secret_header(request: Request, call_next):
    path = request.url.path
    if path in AUTH_WHITELIST or path.startswith(AUTH_WHITELIST_PREFIXES):
        return await call_next(request)

    token = request.headers.get("x-auth-token")
    if token != API_SECRET_TOKEN:
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

    DouYin.update_cookie(params.cookie)
    return {"code": 200, "msg": "Cookie 更新成功"}


@app.get("/video/share/url/parse")
async def share_url_parse(url: str):
    video_share_url = extract_url(url)
    if video_share_url is None:
        return {
            "code": 400,
            "msg": "未检测到有效的分享链接",
        }

    try:
        video_info = await parse_video_share_url(video_share_url)
        return {
            "code": 200,
            "msg": "解析成功",
            "data": dataclasses.asdict(video_info),
        }
    except Exception as err:
        return {
            "code": 500,
            "msg": str(err),
        }


@app.get("/video/id/parse")
async def video_id_parse(source: VideoSource, video_id: str):
    try:
        video_info = await parse_video_id(source, video_id)
        return {
            "code": 200,
            "msg": "解析成功",
            "data": dataclasses.asdict(video_info),
        }
    except Exception as err:
        return {
            "code": 500,
            "msg": str(err),
        }


mcp.setup_server()
