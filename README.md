   * [支持平台](#支持平台)
   * [安装](#安装)
   * [Docker](#docker)
   * [生产部署](#生产部署)
   * [依赖模块](#依赖模块)

Python短视频去水印, 视频目前支持25个平台, 图集目前支持5个平台, 欢迎各位Star。
> 💡tips
> 1. 出现解析失败可在 issue 中提问，请提供可用于复现的平台信息、分享链接.
> 2. 使用时, 请尽量使用app分享链接, 电脑网页版未做充分测试.

# 其他语言版本
- [Golang版本](https://github.com/wujunwei928/parse-video)

---

<div align="center">

##  🚀 GLM Coding 限时优惠！性能强劲 量大管饱

### 🎁 智谱 GLM Coding 超值订阅，邀你一起"薅羊毛"！

**本项目前端多套主体样式和后端逻辑均有用到GLM辅助开发, 绝对性能够用, 又量大管饱.**

[立即开拼，享限时惊喜价, 首购低至4折！](https://www.bigmodel.cn/glm-coding?ic=KUS7WQB5UI)

<img src="resources/BigmodelPoster.png" alt="拼好模活动海报" width="300">

---

</div>

# MCP 支持
本项目现已支持 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/)，提供StreamableHttp方式接入， 接入URL： http://localhost:8000/mcp

# 支持平台
## 图集
| 平台 | 状态 |
|----|----|
| 抖音 | ✔  |
| 快手 | ✔  |
| 小红书 | ✔  |
| 皮皮虾 | ✔  |
| 微博 | ✔  |

## 图集 LivePhoto
| 平台 | 状态 |
|----|----|
| 小红书 | ✔  |
| 抖音 | ✔  |

## 视频
| 平台       | 状态 |
|----------|----|
| 小红书      | ✔  |
| 皮皮虾      | ✔  |
| 抖音短视频    | ✔  |
| 火山短视频    | ✔  |
| 皮皮搞笑     | ✔  |
| 快手短视频    | ✔  |
| 微视短视频    | ✔  |
| 西瓜视频     | ✔  |
| 最右       | ✔  |
| 梨视频      | ✔  |
| 度小视(原全民) | ✔  |
| 逗拍       | ✔  |
| 微博       | ✔  |
| 绿洲       | ✔  |
| 全民K歌     | ✔  |
| 6间房      | ✔  |
| 美拍       | ✔  |
| 新片场      | ✔  |
| 好看视频     | ✔  |
| 虎牙       | ✔  |
| AcFun    | ✔  |
| 央视网     | ✔  |
| 搜狐视频    | ✔  |
| 哔哩哔哩	| ✔  |
| 腾讯视频    | ✔  |
| Twitter/X	| ✔  |

# 运行

## 本地运行

### 使用 uv（推荐）
```shell
# 进入项目根目录
cd parse-video-py

# 创建虚拟环境并安装全部依赖
uv venv && uv pip install -e ".[all]"

# 激活虚拟环境
source .venv/bin/activate
```

### CLI 命令行
```shell
# 安装
uv pip install -e ".[all]"

# 解析视频
parse-video-py parse "https://v.douyin.com/xxx"
parse-video-py parse "https://v.douyin.com/xxx" --format json

# 启动 Web 服务
parse-video-py serve --port 8000

# 查看版本
parse-video-py version
```

### 接口鉴权与抖音 Cookie 配置
```shell
# 解析接口请求头 x-auth-token 的值；不设置时使用旧部署默认值
export API_SECRET_TOKEN='wxd8f9c2a1b3_my_secret_pwd'

# 小程序旧接口请求头 x-api-key 的值；不设置时兼容旧小程序默认值
export MINIPROGRAM_API_KEY='HinsCheung_Love_Video_Parser_2026_No_Copy'

# 页面 / API 更新抖音 Cookie 时使用的管理员密码；不设置时使用旧部署默认值
export DOUYIN_COOKIE_UPDATE_PASSWORD='WhatFuck.1'

# 可选：服务启动时预置抖音 Cookie；生产部署推荐使用 DOUYIN_COOKIE_FILE 持久化
export DOUYIN_COOKIE='你的完整抖音Cookie'

# 可选：页面更新 Cookie 后保存到该文件，服务重启后自动读取
export DOUYIN_COOKIE_FILE='/var/www/douyin/.runtime/douyin_cookie.txt'

# 可选：小程序下载失败域名记录文件
export ERROR_REPORT_FILE='/var/www/douyin/public/uploads/error_domains.json'
```

### 运行app
```shell
uvicorn parse_video_py.web:app --reload
```

## Docker运行
### 构建当前仓库镜像
```bash
git clone --branch v1.1.8 --depth 1 https://github.com/hinspath/parse-video-py.git
cd parse-video-py
docker build -t parse-video-py:v1.1.8 .
```

### 运行 docker 容器, 端口 8000
```bash
docker run -d \
  --name parse-video-py \
  --restart unless-stopped \
  -p 8000:8000 \
  -e API_SECRET_TOKEN='wxd8f9c2a1b3_my_secret_pwd' \
  -e MINIPROGRAM_API_KEY='HinsCheung_Love_Video_Parser_2026_No_Copy' \
  -e DOUYIN_COOKIE_UPDATE_PASSWORD='WhatFuck.1' \
  -e DOUYIN_COOKIE_FILE='/app/.runtime/douyin_cookie.txt' \
  -e ERROR_REPORT_FILE='/app/public/uploads/error_domains.json' \
  -v "$(pwd)/.runtime:/app/.runtime" \
  -v "$(pwd)/public/uploads:/app/public/uploads" \
  parse-video-py:v1.1.8
```

# 生产部署

本节记录当前线上部署方式，默认项目目录为 `/var/www/douyin`，Python 服务由 PM2 管理，nginx 对外提供域名访问。

## 生产路径说明

| 路径 / 名称 | 作用 |
| ---- | ---- |
| `/var/www/douyin` | 项目根目录 |
| `/var/www/douyin/venv` | Python 虚拟环境 |
| `/var/www/douyin/run.sh` | PM2 启动 Python API 的脚本 |
| `/var/www/douyin/src/parse_video_py/web.py` | Web API 主入口 |
| `/var/www/douyin/src/parse_video_py/templates/index.html` | 前端页面 |
| `/var/www/douyin/.runtime/douyin_cookie.txt` | 页面更新后的抖音 Cookie 持久化文件，重启后自动读取 |
| `/var/www/douyin/public/uploads/error_domains.json` | 小程序下载失败域名记录文件 |
| `/etc/nginx/sites-enabled/douyin` | nginx 站点配置 |
| `dy-python-api` | PM2 中 Python API 服务名 |

`.runtime/douyin_cookie.txt` 是敏感文件，不要提交到 GitHub，也不要放到 `public/uploads` 目录。

## 新服务器首次部署

```bash
sudo -i
apt update
apt install -y git python3 python3-venv python3-pip nginx nodejs npm
npm install -g pm2
```

拉取项目：

```bash
rm -rf /var/www/douyin
git clone --branch v1.1.8 https://github.com/hinspath/parse-video-py.git /var/www/douyin
cd /var/www/douyin
```

安装 Python 依赖：

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

创建运行目录：

```bash
mkdir -p /var/www/douyin/.runtime
mkdir -p /var/www/douyin/public/uploads
chmod 700 /var/www/douyin/.runtime
```

写入 `/var/www/douyin/run.sh`：

```bash
cat > /var/www/douyin/run.sh <<'EOF'
#!/bin/bash

export PATH=/usr/local/bin:/usr/bin:$PATH
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

export API_SECRET_TOKEN='wxd8f9c2a1b3_my_secret_pwd'
export MINIPROGRAM_API_KEY='HinsCheung_Love_Video_Parser_2026_No_Copy'
export DOUYIN_COOKIE_UPDATE_PASSWORD='WhatFuck.1'
export DOUYIN_COOKIE_FILE='/var/www/douyin/.runtime/douyin_cookie.txt'
export ERROR_REPORT_FILE='/var/www/douyin/public/uploads/error_domains.json'

cd /var/www/douyin
source venv/bin/activate

echo "------------------------------------------------"
echo "当前 Node 路径: $(which node)"
echo "当前 Python 路径: $(which python)"
echo "------------------------------------------------"

exec uvicorn parse_video_py.web:app --host 127.0.0.1 --port 8002
EOF

chmod +x /var/www/douyin/run.sh
```

启动 PM2：

```bash
pm2 start /var/www/douyin/run.sh --name dy-python-api
pm2 save
pm2 startup
```

如果机器上还有旧的 `dy-node-server`，新版本不再需要它处理 `/api/`，确认 nginx 已经把 `/api/` 转发到 `8002` 后可以停掉旧 Node 服务。

## nginx 配置

编辑 `/etc/nginx/sites-enabled/douyin`：

```nginx
server {
    listen 80;
    server_name douyin.hinscheung.cloud douyin.hins.top;

    location /uploads/ {
        alias /var/www/douyin/public/uploads/;
        expires 30d;
        add_header Access-Control-Allow-Origin *;
        autoindex off;
    }

    location /api/ {
        auth_basic off;
        proxy_buffering off;
        proxy_request_buffering off;
        gzip off;
        tcp_nodelay on;

        proxy_pass http://127.0.0.1:8002;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_connect_timeout 60s;
    }

    location / {
        auth_basic "Restricted Access";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass http://127.0.0.1:8002;
        proxy_buffering off;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

检查并重载 nginx：

```bash
nginx -t
systemctl reload nginx
```

如果没有设置网页访问密码，可以删除 `location /` 中的 `auth_basic` 两行。小程序接口所在的 `/api/` 必须保持 `auth_basic off`。

## Cookie 持久化

前端页面提交 Cookie 后，服务会写入：

```bash
/var/www/douyin/.runtime/douyin_cookie.txt
```

PM2 重启后，服务会自动读取该文件并继续走抖音 Cookie 线路。验证方法：

```bash
cd /var/www/douyin
source venv/bin/activate

python3 - <<'PY'
from parse_video_py import web
from parse_video_py.parser import douyin

print("Cookie 文件:", web.DOUYIN_COOKIE_FILE)
print("文件存在:", web.DOUYIN_COOKIE_FILE.exists())
print("文件长度:", len(web.DOUYIN_COOKIE_FILE.read_text(encoding="utf-8").strip()) if web.DOUYIN_COOKIE_FILE.exists() else 0)
print("内存 Cookie 长度:", len(douyin.GLOBAL_DY_COOKIE))
print("是否已加载:", bool(douyin.GLOBAL_DY_COOKIE))
PY
```

新服务器如果要沿用老服务器 Cookie，复制该文件：

```bash
mkdir -p /var/www/douyin/.runtime
scp root@老服务器IP:/var/www/douyin/.runtime/douyin_cookie.txt /var/www/douyin/.runtime/douyin_cookie.txt
chmod 600 /var/www/douyin/.runtime/douyin_cookie.txt
pm2 restart dy-python-api --update-env
```

## 失败域名记录

小程序下载失败并触发兜底弹窗时，会向 `/api/report_error` 上报域名。前端主页会每 15 秒请求 `/api/get_errors`，显示失败域名列表。

记录文件：

```bash
/var/www/douyin/public/uploads/error_domains.json
```

相关接口：

```bash
# 查看失败域名
curl https://douyin.hins.top/api/get_errors

# 删除单个失败域名
curl -X POST https://douyin.hins.top/api/delete_error \
  -H 'Content-Type: application/json' \
  -H 'x-auth-token: wxd8f9c2a1b3_my_secret_pwd' \
  -d '{"domain":"https://example.com"}'

# 一键清空失败域名
curl -X POST https://douyin.hins.top/api/clear_errors \
  -H 'x-auth-token: wxd8f9c2a1b3_my_secret_pwd'
```

## 部署验证

本机验证 Python API：

```bash
curl -H 'x-auth-token: wxd8f9c2a1b3_my_secret_pwd' \
  'http://127.0.0.1:8002/video/share/url/parse?url=https://v.douyin.com/dRj-CU9n1GQ/'
```

验证小程序旧接口：

```bash
curl -H 'x-api-key: HinsCheung_Love_Video_Parser_2026_No_Copy' \
  'https://douyin.hinscheung.cloud/api/parse?url=https://v.douyin.com/dRj-CU9n1GQ/'
```

查看日志：

```bash
pm2 logs dy-python-api --lines 100
```

## 现有服务器更新

```bash
cd /var/www/douyin

cp -a run.sh run.sh.bak.$(date +%F-%H%M%S)
git fetch --tags origin
git checkout -f tags/v1.1.8

source venv/bin/activate
pip install -r requirements.txt
pip install -e .

chmod +x /var/www/douyin/run.sh
pm2 restart dy-python-api --update-env
pm2 save
```

如果 `git checkout` 覆盖了 `run.sh`，按上面的 `run.sh` 模板重新写入一次。

# 查看前端页面
访问: http://127.0.0.1:8000/

请求接口, 查看json返回
```bash
curl -H 'x-auth-token: wxd8f9c2a1b3_my_secret_pwd' 'http://127.0.0.1:8000/video/share/url/parse?url=视频分享链接' | jq
```
返回格式
```json
{
  "author": {
    "uid": "uid",
    "name": "name",
    "avatar": "https://xxx"
  },
  "title": "记录美好生活#峡谷天花板",
  "video_url": "https://xxx",
  "music_url": "https://yyy",
  "cover_url": "https://zzz"
}
```
| 字段名 | 说明 |
| ---- | ---- |
| author.uid | 视频作者id |
| author.name | 视频作者名称 |
| author.avatar | 视频作者头像 |
| title | 视频标题 |
| video_url | 视频无水印链接 |
| music_url | 视频音乐链接 |
| cover_url | 视频封面 |
| images | 图集图片列表 |
| images.[index].url | 图集图片地址 |
| images.[index].live_photo_url | 图集图片 livephoto 视频地址 |
> 字段除了视频地址, 其他字段可能为空

# 自己写方法调用
```python
import json
import asyncio

from parse_video_py import parse_video_share_url, parse_video_id, VideoSource

# 根据分享链接解析
video_info = asyncio.run(parse_video_share_url("分享链接"))
print(
    "解析分享链接：\n",
    json.dumps(video_info, ensure_ascii=False, indent=4, default=lambda x: x.__dict__),
    "\n",
)

# 根据视频id解析
video_info = asyncio.run(
    parse_video_id(VideoSource.DouYin, "视频ID")
)
print(
    "解析视频ID：\n",
    json.dumps(video_info, ensure_ascii=False, indent=4, default=lambda x: x.__dict__),
    "\n",
)
```


# 依赖模块
| 模块        | 作用                                   |
|-------------|--------------------------------------|
| fastapi     | web框架                                |
| fastapi-mcp | 支持MCP                                |
| httpx       | HTTP 和 REST 客户端                      |
| parsel      | 解析html页面                             |
| pre-commit  | 对git代码提交前进行检查，结合flake8，isort，black使用 |
| flake8      | 工程化：代码风格一致性                          |
| isort       | 工程化：格式化导入package                     |
| black       | 工程化：代码格式化                            |
