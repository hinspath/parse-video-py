# Changelog

所有重要变更均会记录在此文件中。

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
