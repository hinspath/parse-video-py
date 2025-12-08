import os
import re
import secrets
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi_mcp import FastApiMCP
from pydantic import BaseModel

# 【关键】导入原来的通用解析函数 (处理快手、小红书等)
from parser import VideoSource, parse_video_id, parse_video_share_url
# 【关键】导入我们要使用的特定抖音解析类
from parser.douyin import DouYin

app = FastAPI()

mcp = FastApiMCP(app)
mcp.mount_http()

templates = Jinja2Templates(directory="templates")

# =========================================================
# 模型定义
# =========================================================
class CookieUpdateParams(BaseModel):
    password: str
    cookie: str

# =========================================================
# 鉴权配置
# =========================================================
MY_SECRET_KEY = os.getenv("API_SECRET_TOKEN", "wxd8f9c2a1b3_my_secret_pwd")

@app.middleware("http")
async def verify_secret_header(request: Request, call_next):
    # 白名单路径
    whitelist = [
        "/", 
        "/docs", 
        "/openapi.json", 
        "/favicon.ico", 
        "/api/update_cookie",   
        "/video/share/url/parse" 
    ]
    
    if request.url.path in whitelist:
        return await call_next(request)

    token = request.headers.get("x-auth-token")
    if token != MY_SECRET_KEY:
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "Permission Denied"}
        )

    return await call_next(request)

# =========================================================
# 辅助函数
# =========================================================
def get_auth_dependency():
    basic_auth_username = os.getenv("PARSE_VIDEO_USERNAME")
    basic_auth_password = os.getenv("PARSE_VIDEO_PASSWORD")
    if not (basic_auth_username and basic_auth_password):
        return []
    security = HTTPBasic()
    def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
        correct_username = secrets.compare_digest(credentials.username, basic_auth_username)
        correct_password = secrets.compare_digest(credentials.password, basic_auth_password)
        if not (correct_username and correct_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Basic"},
            )
        return credentials
    return [Depends(verify_credentials)]

# =========================================================
# 路由
# =========================================================

@app.get("/", response_class=HTMLResponse, dependencies=get_auth_dependency())
async def read_item(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "Video Parser"},
    )

@app.post("/api/update_cookie")
async def update_cookie_api(params: CookieUpdateParams):
    if params.password != "WhatFuck.1":
        return JSONResponse(status_code=403, content={"code": 403, "msg": "密码错误"})
    if not params.cookie:
        return JSONResponse(status_code=400, content={"code": 400, "msg": "Cookie 不能为空"})

    # 更新 DouYin 类的 Cookie
    DouYin.update_cookie(params.cookie)
    return {"code": 200, "msg": "Cookie 更新成功！"}

@app.get("/video/share/url/parse", dependencies=get_auth_dependency())
async def share_url_parse(url: str):
    try:
        # 1. URL 清洗 (提取链接)
        url_reg = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
        match = url_reg.search(url)
        video_share_url = match.group() if match else url

        # ========================================================
        # 【核心修复】智能路由分发
        # ========================================================
        
        # 检查是否包含抖音关键字 (douyin 或 iesdouyin)
        if "douyin" in video_share_url:
            # 抖音链接 -> 走我们魔改的 DouYin 类 (支持实况 + Cookie池)
            print(f"[Router] Detected Douyin URL, using specialized parser...")
            parser = DouYin()
            video_info = await parser.parse_share_url(video_share_url)
        else:
            # 其他链接 (快手/小红书/视频号) -> 走原来的通用解析函数
            # 原来的 parse_video_share_url 会自动根据域名分发给 kuaishou.py, xiaohongshu.py 等
            print(f"[Router] Detected other URL, using default parser...")
            video_info = await parse_video_share_url(video_share_url)

        return {"code": 200, "msg": "解析成功", "data": video_info.__dict__}

    except Exception as err:
        print(f"[API Error] {err}")
        return {"code": 500, "msg": str(err)}

# 保留旧的 ID 解析接口
@app.get("/video/id/parse", dependencies=get_auth_dependency())
async def video_id_parse(source: VideoSource, video_id: str):
    try:
        video_info = await parse_video_id(source, video_id)
        return {"code": 200, "msg": "解析成功", "data": video_info.__dict__}
    except Exception as err:
        return {"code": 500, "msg": str(err)}

mcp.setup_server()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
