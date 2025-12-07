import os
import re
import secrets
# 引入 JSONResponse
from fastapi.responses import HTMLResponse, JSONResponse
# 确保你的 parser.py 文件在同级目录
from parser import VideoSource, parse_video_id, parse_video_share_url

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from fastapi_mcp import FastApiMCP

app = FastAPI()

mcp = FastApiMCP(app)
mcp.mount_http()

templates = Jinja2Templates(directory="templates")

# =========================================================
# 鉴权配置
# =========================================================
MY_SECRET_KEY = os.getenv("API_SECRET_TOKEN", "wxd8f9c2a1b3_my_secret_pwd")

@app.middleware("http")
async def verify_secret_header(request: Request, call_next):
    # 白名单路径
    if request.url.path in ["/", "/docs", "/openapi.json", "/favicon.ico"]:
        return await call_next(request)

    # 校验密码 (x-auth-token)
    token = request.headers.get("x-auth-token")
    if token != MY_SECRET_KEY:
        return JSONResponse(
            status_code=403,
            content={"code": 403, "msg": "Permission Denied: Invalid Secret Token"}
        )

    response = await call_next(request)
    return response

# =========================================================
# 辅助函数 (去掉了可能导致报错的类型标注)
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
        context={
            "title": "Video Parser",
        },
    )

@app.get("/video/share/url/parse", dependencies=get_auth_dependency())
async def share_url_parse(url: str):
    # 简化正则，防止报错
    try:
        url_reg = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
        match = url_reg.search(url)
        video_share_url = match.group() if match else url

        video_info = await parse_video_share_url(video_share_url)
        return {"code": 200, "msg": "解析成功", "data": video_info.__dict__}
    except Exception as err:
        print(f"Error parsing URL: {err}") # 打印日志方便排查
        return {"code": 500, "msg": str(err)}

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
