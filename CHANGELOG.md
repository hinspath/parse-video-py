# Changelog

## [v1.1.23] - 2026-06-27

### 新增

- **小程序微信登录态校验**：新增 `/api/wx/login`，后端使用微信小程序 `code2session` 换取 `openid` 后签发短期 `x-wx-session`。
- **小程序接口灰度开关**：新增 `MINIPROGRAM_AUTH_MODE`，默认 `api_key` 兼容旧小程序；设置为 `wechat` 后 `/api/parse` 必须携带有效 `x-wx-session`，避免解包后仅凭前端 `x-api-key` 直接调用接口。

### 部署

- 新增环境变量：`WECHAT_MINIPROGRAM_APPID`、`WECHAT_MINIPROGRAM_SECRET`、`WECHAT_SESSION_SECRET`、`WECHAT_SESSION_TTL_SECONDS`。

---
所有重要变更均会记录在此文件中。

## [v1.1.22] - 2026-05-06

### 调整

- **Admin 提前鉴权**：访问 `/admin` 时先触发浏览器 Basic Auth，后台按钮操作可直接使用当前登录态，不再要求页面内重复输入管理员密码。
- **移除首页 GitHub 链接**：主页面页脚不再展示 GitHub 入口。

---

## [v1.1.21] - 2026-05-06

### 调整

- **Web 下载改回官方 CDN**：Web 页面预览、单个下载、下载全部、封面和音乐下载均使用官方解析地址，不再使用 `dl.hins.top` 代理下载地址；`download_url` 字段仍保留给小程序使用。

---

## [v1.1.20] - 2026-05-06

### 修复

- **Web 预览视频无法播放**：前端预览视频时先通过 `/api/resolve_redirect` 解析抖音播放地址到最终 CDN，再写入 `<video>`，避免浏览器直接播放 `www.douyin.com/aweme/v1/play` 失败。
- **代理下载文件无后缀**：`/api/download` 根据上游 `Content-Type` 或原始路径返回 `download.mp4`、`download.jpg` 等带扩展名的 `Content-Disposition`，前端触发下载时也会补齐扩展名。

---

## [v1.1.19] - 2026-05-06

### 修复

- **长视频代理下载中断**：`/api/download` 在上游 CDN 长连接中途断开时，会使用 `Range` 从已发送字节位置续拉，并保持给小程序的一条完整 `200` 下载响应，减少大文件下载到一半失败或重新开始的问题。

---

## [v1.1.18] - 2026-05-06

### 新增

- **多平台用户 Cookie 输入**：首页“自定义 Cookies”补齐小红书、抖音、快手、B站、微博五个平台入口，保存到当前浏览器。
- **多平台全局 Cookie 管理**：Admin 页面补齐五个平台全局 Cookie 设置，并新增 `.runtime/platform_cookies.json` 持久化文件；抖音保存后仍会同步到旧的 `.runtime/douyin_cookie.txt` 并立即生效。

### 调整

- **后台 Cookie 保存更安全**：Admin 页面留空表示保持原值，输入 `CLEAR` 才清空对应平台，避免误删其它已保存 Cookie。

---

## [v1.1.17] - 2026-05-06

### 新增

- **重构 Web 前端**：主页面改为左右分栏的解析工具界面，支持视频清晰度、图集、Live Photo、弹窗预览和下载全部。
- **新增 Admin 页面**：新增 `/admin` 管理页，集中处理全局抖音 Cookie、下载代理开关、失败域名删除和一键清空。
- **用户 Cookie 优先**：主页面的“我的 Cookies”只保存在用户浏览器；解析抖音时优先使用用户自己的 Cookie，没有设置时再使用服务器全局 Cookie。

### 调整

- **移除主页面敏感配置**：主页面不再展示 API Token、全局 Cookie 或失败域名管理，敏感操作迁移到 Admin 页面。
- **预览与下载分离**：页面预览继续使用官方 CDN 地址，下载按钮优先使用后端签发的代理下载地址。

---

## [v1.1.16] - 2026-05-06

### 修复

- **快手单图作品解析**：快手 `SINGLE_PICTURE` 内容没有视频和图集数组时，返回封面作为图片内容，并尽量补充音乐地址，避免小程序提示未解析到有效内容。

---

## [v1.1.15] - 2026-05-06

### 修复

- **快手新版 SSR 图集解析**：兼容 `window.INIT_STATE` 页面结构和 `cdnList` 图集字段，修复快手图集解析失败。

---

## [v1.1.14] - 2026-05-06

### 修复

- **快手代理下载请求头**：`/api/download` 根据目标域名设置平台 Referer，修复部分快手 CDN 经代理下载时 502 的问题。

---

## [v1.1.13] - 2026-05-06

### 修复

- **小程序代理下载反复重试**：`/api/download` 不再把客户端 `Range` 请求头转发给上游，并将上游 `206 Partial Content` 规范化为完整文件流响应，避免微信下载进度到 70%-80% 后重新开始。

---

## [v1.1.12] - 2026-05-06

### 新增

- **后台下载代理开关**：新增 `/api/download_proxy_mode`，Web 管理页可一键开启或暂停自有域名下载代理。暂停后新解析结果不再下发 `download_url`，小程序会回到官方 CDN；已签发的代理链接也会被 `/api/download` 立即拒绝，避免继续消耗代理流量。

---

## [v1.1.11] - 2026-05-05

### 新增

- **下载代理接口**：新增 `/api/download` 签名下载代理，小程序可统一通过自有域名下载视频、封面、图集和实况视频，减少微信合法下载域名维护成本。
- **代理下载字段**：解析结果新增 `download_url`、`cover_download_url`、`qualities.[index].download_url`、`images.[index].download_url` 和 `images.[index].live_photo_download_url`。

---

## [v1.1.10] - 2026-05-05

### 优化

- **精简抖音清晰度列表**：同一分辨率下只保留码率最高的视频地址，避免页面和小程序展示多个重复的 720P/540P 档位。

---

## [v1.1.9] - 2026-05-05

### 新增

- **抖音视频清晰度列表**：解析抖音普通视频时从 `video.bit_rate` 提取多个清晰度地址，按分辨率和码率排序后返回 `video_urls` 和兼容别名 `qualities`，同时保留旧字段 `video_url`。
- **前端清晰度下载入口**：当接口返回多个清晰度时，页面展示每个清晰度的独立下载按钮。

---

## [v1.1.8] - 2026-05-05

### 修复

- **持久化抖音 Cookie**：页面更新 Cookie 后写入 `.runtime/douyin_cookie.txt`，PM2 重启后自动读取，避免重启后掉回无 Cookie 线路。
- **恢复失败域名管理**：前端主页重新轮询 `/api/get_errors`，失败域名显示为 `https://域名`，支持单个删除和一键清空。
- **完善生产部署文档**：README 增加 `/var/www/douyin`、PM2、nginx、Cookie 迁移和失败域名文件路径说明。

---

## [v1.1.7] - 2026-05-05

### 修复

- **恢复小程序旧接口兼容**：新增 `/api/parse`、`/api/analysis`、`/api/resolve_redirect`、`/api/get_errors`、`/api/report_error`，兼容旧小程序的 `x-api-key` 调用方式。
- **兼容旧返回字段**：解析结果补充 `url`、`cover`、`local_url`、`local_live_photo_url`，避免小程序升级后取不到原有字段。

---

## [v1.1.6] - 2026-05-05

### 修复

- **放行 favicon.png**：避免前端页面请求 favicon 时被 `x-auth-token` 中间件拦截为 403。
- **更新部署文档**：README 改为当前 `x-auth-token`、抖音 Cookie 和本仓库 Docker 构建方式，移除过期 Basic Auth / 作者镜像示例。

---

## [v1.1.5] - 2026-05-05

### 修复

- **兼容 PyExecJS 异常式签名输出**：当 `execjs` 抛出包含 `["ok","签名"]` 的异常时，直接提取签名继续请求抖音强解析接口。
- **Node 签名输出兼容**：`node` 兜底签名返回非 0 状态但 stdout 已包含签名时，也会提取签名使用。

---

## [v1.1.4] - 2026-05-05

### 修复

- **抖音签名兜底**：`execjs` 调用 `signer.js` 失败时，自动改用系统 `node` 执行同一签名脚本，恢复旧部署环境里的签名生成路径。
- **签名错误日志**：输出 `execjs` / `node` 的失败原因，方便 PM2 日志排查。

---

## [v1.1.3] - 2026-05-05

### 修复

- **按旧部署版逻辑恢复抖音实况图集解析**：优先使用 Cookie + `signer.js` 的 `aweme/detail` API，并按旧版方式从 `video.play_addr` / `video.download_addr` 提取 `live_photo_url`。
- **兼容新图集结构**：支持 `image_post_info.images`、`display_image` 等字段，避免图片能解析但实况地址为空。

---

## [v1.1.2] - 2026-05-05

### 修复

- **前端实况图集下载入口**：图集项存在实况视频地址时显示“下载实况视频”按钮，并兼容多个字段名。
- **抖音实况地址提取**：递归识别图片项中的嵌套视频播放地址，提升 Live Photo 图集解析成功率。

---

## [v1.1.1] - 2026-05-05

### 修复

- **抖音无 Cookie 解析稳定性**：抖音 HTML 兜底解析固定使用移动 Safari 请求头，避免随机 UA 在部分服务器上拿不到 `_ROUTER_DATA`。

---

## [v0.0.3] - 2026-04-19

### 新增功能

- **新增 CLI 命令行工具**：支持 `version`/`parse`/`serve` 三个子命令，可通过 `parse-video-py` 入口直接使用
- **新增 CLI `-h` 简写**：所有命令支持 `-h` 作为 `--help` 的简写
- **新增 pyproject.toml**：使用 hatchling 构建，支持 `[web]`/`[cli]`/`[dev]` 可选依赖安装
- **新增包公开 API**：支持 `from parse_video_py import VideoSource, parse_video_share_url` 直接调用

### 架构重构

- **迁移到 src 标准布局**：`parser/`、`utils/`、`templates/` 统一迁移到 `src/parse_video_py/` 下
- **uv 包管理**：从 venv + requirements.txt 迁移到 uv + pyproject.toml，支持 `uv pip install -e ".[all]"`
- **Web 服务拆分**：从 `main.py` 提取到 `src/parse_video_py/web.py`，`main.py` 改为薄入口
- **URL 工具统一**：`URL_REG` 正则和 `extract_url` 提取到 `utils.py`，消除 web/cli 模块间的重复定义

### 优化改进

- **Web 序列化**：使用 `dataclasses.asdict()` 替代 `__dict__`，正确处理嵌套 dataclass 序列化
- **Auth 依赖缓存**：Basic Auth 依赖在模块加载时构建一次，避免每个路由重复调用
- **批量解析并发限制**：CLI 批量解析添加 `Semaphore(10)` 防止无界并发
- **Dockerfile 更新**：使用 uv 安装依赖，适配 src 布局
- **CI 更新**：GitHub Actions 改用 `astral-sh/setup-uv`

---

## [v0.0.2] - 2026-04-18

### 新增功能

- **新增 B站(哔哩哔哩) 视频解析**：支持 bilibili.com、b23.tv、m.bilibili.com 域名
- **新增 Twitter/X 视频解析**：支持 twitter.com、x.com、t.co 域名
- **新增微博图集解析**：支持微博图片帖子的图集批量提取
- **新增抖音 Live Photo 实况照片支持**：通过 slidesinfo API 提取实况照片视频
- **新增图集批量下载功能**：前端支持图集图片批量下载 (#58)
- **新增 MCP 支持**：通过 StreamableHttp 方式接入 MCP 协议，接入 URL: `/mcp`
- **新增主题样式选择**：前端页面支持多种主题风格切换
- **新增 Basic Auth 自定义认证**：支持通过环境变量自定义用户名密码 (#48)
- **新增 Claude Code 集成**：添加 CLAUDE.md 项目指引和 GitHub Actions CI 工作流

### 优化改进

- **小红书图集图片高清化**：图集图片使用高清地址，优化图片域名替换逻辑 (#45)
- **抖音图集解析音频**：支持抖音图集内容的音频提取 (#70)
- **单元测试覆盖**：添加核心模块单元测试，pre-commit 支持提交时自动运行测试
- **分享链接正则优化**：优化 URL 匹配正则表达式，增强无效输入处理鲁棒性 (#74)
- **依赖管理优化**：整理 requirements.txt 依赖项

### Bug 修复

- **修复无效分享链接导致崩溃**：无效 URL 输入不再导致服务异常
- **修复小红书图片域名替换逻辑**：当图片 URL 不包含 notes_pre_post 时使用原域名

---

## [v0.0.1] - 初始版本

### 基础功能

- 支持 20+ 平台视频去水印解析
- 支持 4 平台图集解析（抖音、快手、小红书、皮皮虾）
- 支持 LivePhoto 解析（小红书）
- FastAPI Web 服务 + REST API 接口
- 前端解析页面
- Docker 部署支持
