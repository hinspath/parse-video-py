import os
import re
import uvicorn
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi_mcp import FastApiMCP
from pydantic import BaseModel

# 导入解析逻辑
from parser import VideoSource, parse_video_id, parse_video_share_url
from parser.douyin import DouYin

app = FastAPI()

mcp = FastApiMCP(app)
mcp.mount_http()

templates = Jinja2Templates(directory="templates")

# =========================================================
# 1. 鉴权配置 & 模型
# =========================================================

# 获取你的密钥
MY_SECRET_KEY = os.getenv("API_SECRET_TOKEN", "wxd8f9c2a1b3_my_secret_pwd")

class CookieUpdateParams(BaseModel):
    password: str
    cookie: str

# =========================================================
# 2. 核心鉴权中间件 (The Guard)
# =========================================================
@app.middleware("http")
async def verify_secret_header(request: Request, call_next):
    # 【重点修改】白名单：只放行不需要 Token 的路径
    # 1. /docs, /openapi.json : 方便你看文档
    # 2. /api/update_cookie : 因为它内部有单独的密码判断
    # 3. / : 首页
    whitelist = [
        "/", 
        "/docs", 
        "/openapi.json", 
        "/favicon.ico", 
        "/api/update_cookie" 
    ]
    
    # 如果请求路径在白名单里，直接放行 (比如 Cookie 更新接口)
    if request.url.path in whitelist:
        return await call_next(request)

    # 【拦截逻辑】其他所有接口 (包括解析接口)，必须检查 Header
    token = request.headers.get("x-auth-token")
    
    # 如果 Token 不对，直接拦截，返回 403
    if token != MY_SECRET_KEY:
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "鉴权失败：请在 Header 中提供正确的 x-auth-token"}
        )

    return await call_next(request)

# =========================================================
# 3. 路由定义
# =========================================================

@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "Video Parser"},
    )

# --- Cookie 更新接口 (白名单放行，内部校验密码) ---
@app.post("/api/update_cookie")
async def update_cookie_api(params: CookieUpdateParams):
    # 这里是你单独的密码逻辑
    if params.password != "WhatFuck.1":
        return JSONResponse(status_code=403, content={"code": 403, "msg": "管理密码错误"})
    if not params.cookie:
        return JSONResponse(status_code=400, content={"code": 400, "msg": "Cookie 不能为空"})

    DouYin.update_cookie(params.cookie)
    return {"code": 200, "msg": "Cookie 更新成功！"}

# --- 视频解析接口 (被中间件拦截，必须带 Header) ---
@app.get("/video/share/url/parse")
async def share_url_parse(url: str):
    try:
        url_reg = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
        match = url_reg.search(url)
        video_share_url = match.group() if match else url

        if "douyin" in video_share_url:
            print(f"[Router] Detected Douyin URL...")
            parser = DouYin()
            video_info = await parser.parse_share_url(video_share_url)
        else:
            print(f"[Router] Detected other URL...")
            video_info = await parse_video_share_url(video_share_url)

        return {"code": 200, "msg": "解析成功", "data": video_info.__dict__}

    except Exception as err:
        print(f"[API Error] {err}")
        return {"code": 500, "msg": str(err)}

# --- ID 解析接口 (被中间件拦截，必须带 Header) ---
@app.get("/video/id/parse")
async def video_id_parse(source: VideoSource, video_id: str):
    try:
        video_info = await parse_video_id(source, video_id)
        return {"code": 200, "msg": "解析成功", "data": video_info.__dict__}
    except Exception as err:
        return {"code": 500, "msg": str(err)}

mcp.setup_server()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
