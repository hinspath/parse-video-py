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

# 导入解析器
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
    # 白名单路径：放行静态资源、文档、以及我们的 Cookie 更新接口
    whitelist = [
        "/", 
        "/docs", 
        "/openapi.json", 
        "/favicon.ico", 
        "/api/update_cookie",   # 允许直接访问 Cookie 更新
        "/video/share/url/parse" # 允许直接访问解析接口 (如果你希望前端也能用)
    ]
    
    if request.url.path in whitelist:
        return await call_next(request)

    # 这里的逻辑保留你原有的 Token 校验
    token = request.headers.get("x-auth-token")
    if token != MY_SECRET_KEY:
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "Permission Denied"}
        )

    response = await call_next(request)
    return response

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

# 【API】更新 Cookie
@app.post("/api/update_cookie")
async def update_cookie_api(params: CookieUpdateParams):
    if params.password != "WhatFuck.1":
        return JSONResponse(status_code=403, content={"code": 403, "msg": "密码错误"})
    
    if not params.cookie:
        return JSONResponse(status_code=400, content={"code": 400, "msg": "Cookie 不能为空"})

    # 更新解析器状态
    DouYin.update_cookie(params.cookie)
    return {"code": 200, "msg": "Cookie 更新成功！解析器优先使用 Mode A (API方案)"}

# 【API】解析 URL
@app.get("/video/share/url/parse", dependencies=get_auth_dependency())
async def share_url_parse(url: str):
    try:
        # URL 清洗
        url_reg = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
        match = url_reg.search(url)
        video_share_url = match.group() if match else url

        # 调用双模解析器
        parser = DouYin()
        video_info = await parser.parse_share_url(video_share_url)

        return {"code": 200, "msg": "解析成功", "data": video_info.__dict__}
    except Exception as err:
        print(f"[API Error] {err}")
        return {"code": 500, "msg": str(err)}

# 保留 ID 解析接口 (如有需要)
# @app.get("/video/id/parse", ...)

mcp.setup_server()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
