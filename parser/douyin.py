import json
import re
import os
import execjs
from urllib.parse import parse_qs, urlparse, urlencode
import httpx
from .base import BaseParser, ImgInfo, VideoAuthor, VideoInfo

# 全局变量存储 Cookie
GLOBAL_DY_COOKIE = ''

class DouYin(BaseParser):
    """
    抖音双模解析器
    Mode A: V1 API (支持实况，需Cookie+签名)
    Mode B: 原版 HTML解析 (兜底方案，无需Cookie，可能无实况)
    """

    def __init__(self):
        super().__init__()
        self.js_ctx = self._load_js()

    @classmethod
    def update_cookie(cls, new_cookie):
        global GLOBAL_DY_COOKIE
        GLOBAL_DY_COOKIE = new_cookie.strip()
        print(f"[Config] Cookie 已更新")

    def _load_js(self):
        """加载签名算法"""
        try:
            # 寻找 signer.js
            current_dir = os.path.dirname(os.path.abspath(__file__))
            paths = [
                os.path.join(current_dir, "..", "signer.js"), 
                os.path.join(current_dir, "signer.js"),
                "signer.js"
            ]
            for p in paths:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        return execjs.compile(f.read())
            print("[WARN] signer.js 未找到，Mode A 将不可用")
            return None
        except: return None

    def _sign(self, query, ua):
        if not self.js_ctx: return ""
        try: return self.js_ctx.call("get_sign", query, ua)
        except: return ""

    async def parse_share_url(self, share_url: str) -> VideoInfo:
        # 1. 统一提取 Video ID
        video_id = await self._extract_video_id(share_url)
        if not video_id:
            raise ValueError("无法解析视频 ID")
        
        print(f"[Main] Target ID: {video_id}")

        # 2. 尝试 Mode A (API 强力模式)
        if GLOBAL_DY_COOKIE:
            try:
                print("[Main] 正在尝试 Mode A (API解析)...")
                return await self._parse_mode_a(video_id)
            except Exception as e:
                print(f"[Main] Mode A 失败 ({e})，正在切换到 Mode B...")
        else:
            print("[Main] 未设置 Cookie，直接使用 Mode B...")

        # 3. 尝试 Mode B (原版 HTML 兜底)
        return await self._parse_mode_b(video_id)

    # =================================================================
    # 工具：提取 ID
    # =================================================================
    async def _extract_video_id(self, url):
        try:
            # 如果链接本身包含ID
            match = re.search(r'/(?:video|note|slides)/(\d+)', url)
            if match: return match.group(1)

            # 否则跟随跳转 (v.douyin.com)
            headers = { "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1" }
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0, headers=headers) as client:
                resp = await client.get(url)
                final_url = str(resp.url)
            
            match = re.search(r'/(?:video|note|slides)/(\d+)', final_url)
            return match.group(1) if match else ""
        except: return ""

    # =================================================================
    # Mode A: API + 签名 (支持实况)
    # =================================================================
    async def _parse_mode_a(self, video_id):
        PC_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        api_url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
        
        params = {
            "aweme_id": video_id,
            "aid": "6383",
            "device_platform": "webapp",
            "pc_client_type": "1",
            "version_code": "190500",
            "version_name": "19.5.0",
            "cookie_enabled": "true",
            "platform": "PC",
            "downlink": "10"
        }
        
        query_str = urlencode(params)
        abogus = self._sign(query_str, PC_UA)
        final_url = f"{api_url}?{query_str}&a_bogus={abogus}"
        
        headers = {
            "User-Agent": PC_UA,
            "Cookie": GLOBAL_DY_COOKIE,
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json"
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(final_url, headers=headers)
            # 检查响应
            if not resp.text or resp.status_code != 200:
                raise ValueError("API Network Error")
            try:
                data = resp.json()
            except:
                raise ValueError("API returned non-JSON")

        detail = data.get("aweme_detail")
        if not detail: raise ValueError("Empty detail")

        # 提取数据
        images = []
        if "images" in detail:
            for img in detail["images"]:
                # 图片地址
                url = img.get("url_list", [""])[-1] # 取最后一个通常更高清
                
                # === 修复开始：实况图去水印逻辑 ===
                live = ""
                if "video" in img: 
                    # 实况图视频信息在 video 字段
                    v = img["video"]
                    # 优先取 play_addr，其次 download_addr
                    # 关键点：必须使用 .replace("playwm", "play") 去除水印
                    addr_info = v.get("play_addr") or v.get("download_addr")
                    if addr_info and "url_list" in addr_info:
                        url_list = addr_info["url_list"]
                        if url_list:
                            # 取最后一个链接，并替换 playwm 为 play
                            live = url_list[-1].replace("playwm", "play")
                # === 修复结束 ===

                images.append(ImgInfo(url=url, live_photo_url=live))
        
        # 视频
        video_url = ""
        if not images and "video" in detail:
             # V1 接口视频提取，同样做去水印处理
             if "play_addr" in detail["video"]:
                 v_list = detail["video"]["play_addr"].get("url_list", [])
                 if v_list:
                     video_url = v_list[-1].replace("playwm", "play")

        return VideoInfo(
            video_url=video_url,
            cover_url=detail.get("video", {}).get("cover", {}).get("url_list", [""])[0],
            title=detail.get("desc", ""),
            images=images,
            author=VideoAuthor(
                uid=detail.get("author", {}).get("sec_uid", ""),
                name=detail.get("author", {}).get("nickname", ""),
                avatar=detail.get("author", {}).get("avatar_thumb", {}).get("url_list", [""])[0]
            )
        )

    # =================================================================
    # Mode B: 原版 HTML 解析 (严格还原)
    # =================================================================
    async def _parse_mode_b(self, video_id):
        print(f"[Main] 正在运行 Mode B (原版解析)... ID: {video_id}")
        
        # 1. 构造 iesdouyin 链接 (原版逻辑)
        req_url = f"https://www.iesdouyin.com/share/video/{video_id}/"
        
        # 2. 发送请求 (原版 headers)
        headers = {
             "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1"
        }
        
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(req_url, headers=headers)
            html = response.text

        # 3. 正则提取 (严格使用原版 regex)
        pattern = re.compile(
            pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
            flags=re.DOTALL,
        )
        find_res = pattern.search(html)

        if not find_res or not find_res.group(1):
            raise ValueError("Mode B Failed: 无法从 HTML 提取 _ROUTER_DATA")

        json_data = json.loads(find_res.group(1).strip())

        # 4. 解析 loaderData (严格原版逻辑)
        data = None
        if isinstance(json_data, dict) and "loaderData" in json_data:
            # 原版逻辑：检查 loaderData 里的 key
            original_video_info = None
            
            # 模糊匹配寻找 videoInfoRes
            for key, val in json_data["loaderData"].items():
                if isinstance(val, dict) and "videoInfoRes" in val:
                    original_video_info = val["videoInfoRes"]
                    break
            
            if not original_video_info:
                raise ValueError("Mode B Failed: loaderData 中未找到 videoInfoRes")

            if len(original_video_info["item_list"]) == 0:
                 raise ValueError("Mode B Failed: item_list 为空")

            data = original_video_info["item_list"][0]
        else:
            raise ValueError("Mode B Failed: 未知的数据结构")

        # 5. 提取内容
        images = []
        if "images" in data and isinstance(data["images"], list):
            for img in data["images"]:
                # 原版逻辑：获取第一个 url，且优先非 webp
                url_list = img.get("url_list", [])
                image_url = ""
                for u in url_list:
                    if u and not u.endswith(".webp"):
                        image_url = u
                        break
                if not image_url and url_list: image_url = url_list[0]
                
                # === 修复开始：Mode B 也尝试获取实况 ===
                live = "" 
                if "video" in img:
                    # 有时候 Mode B 数据里也有 video 字段
                    play_addr = img["video"].get("play_addr", {}).get("url_list", [])
                    if play_addr:
                        live = play_addr[-1].replace("playwm", "play")
                # === 修复结束 ===

                images.append(ImgInfo(url=image_url, live_photo_url=live))

        # 视频地址
        video_url = ""
        if not images and "video" in data:
            play_addr = data["video"].get("play_addr", {})
            if "url_list" in play_addr:
                 video_url = play_addr["url_list"][0].replace("playwm", "play")

        return VideoInfo(
            video_url=video_url,
            cover_url=data.get("video", {}).get("cover", {}).get("url_list", [""])[0],
            title=data.get("desc", ""),
            images=images,
            author=VideoAuthor(
                uid=data.get("author", {}).get("sec_uid", ""),
                name=data.get("author", {}).get("nickname", ""),
                avatar=data.get("author", {}).get("avatar_thumb", {}).get("url_list", [""])[0]
            )
        )

    # 存根接口保持兼容
    async def parse_video_id(self, v): return None
    def _get_request_url_by_video_id(self, v): return ""
    def _parse_video_id_from_path(self, p): return ""
    async def _parse_app_share_url(self, s): return ""
    def _get_no_webp_url(self, l): return l[0] if l else ""
    def _is_note_content(self, h, s): return True
