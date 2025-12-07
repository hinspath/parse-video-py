import json
import re
from urllib.parse import parse_qs, urlparse, unquote
import httpx
from .base import BaseParser, ImgInfo, VideoAuthor, VideoInfo

class DouYin(BaseParser):
    """
    抖音解析器 (Live Photo 修复版)
    """

    async def parse_share_url(self, share_url: str) -> VideoInfo:
        # 1. 基础 URL 解析
        parsed_url = urlparse(share_url)
        host = parsed_url.netloc

        if host in ["www.iesdouyin.com", "www.douyin.com"]:
            video_id = self._parse_video_id_from_path(share_url)
            share_url = self._get_request_url_by_video_id(video_id)
        elif host == "v.douyin.com":
            video_id = await self._parse_app_share_url(share_url)
            share_url = self._get_request_url_by_video_id(video_id)
        else:
            raise ValueError(f"Douyin not support this host: {host}")

        print(f"[DEBUG] Video ID: {video_id}")

        # ==================================================================
        # 策略: 模拟 iPhone 17 + 清除旧 Cookie
        # 这里的关键是不要带失效的 s_v_web_id，否则会被降级处理
        # ==================================================================
        mobile_headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Referer": "https://www.douyin.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Upgrade-Insecure-Requests": "1"
        }
        
        # 使用 Session 保持连接，但不预设 Cookie
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, headers=mobile_headers) as client:
            # 有时需要在 Header 里加一个 ttwid，但通常直接请求空 Cookie 效果更好
            response = await client.get(share_url)
            response.raise_for_status()

        html_text = response.text
        json_data = None
        
        # 解析 RENDER_DATA (Mobile 版通常包含完整数据)
        pattern_render = re.compile(r'<script id="RENDER_DATA" type="application/json">(.*?)</script>', re.DOTALL)
        find_res = pattern_render.search(html_text)
        
        if find_res and find_res.group(1):
            raw_json = find_res.group(1).strip()
            try:
                json_data = json.loads(unquote(raw_json))
            except:
                try:
                    json_data = json.loads(raw_json)
                except Exception as e:
                    print(f"[ERROR] JSON decode failed: {e}")
        
        # 备用：_ROUTER_DATA
        if not json_data:
            pattern_router = re.compile(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", re.DOTALL)
            find_res = pattern_router.search(html_text)
            if find_res:
                try:
                    json_data = json.loads(find_res.group(1).strip())
                except:
                    pass

        # ==================================================================
        # 数据提取逻辑
        # ==================================================================
        data = None
        if isinstance(json_data, dict):
            # 路径A: app.videoDetail (最常见)
            if "app" in json_data and "videoDetail" in json_data["app"]:
                 data = json_data["app"]["videoDetail"]
            # 路径B: loaderData
            elif "loaderData" in json_data:
                for k, v in json_data["loaderData"].items():
                    if isinstance(v, dict) and "videoInfoRes" in v:
                        info = v["videoInfoRes"]
                        if "item_list" in info and info["item_list"]:
                            data = info["item_list"][0]
                            break
            # 路径C: aweme_details
            elif "aweme_details" in json_data and json_data["aweme_details"]:
                 data = json_data["aweme_details"][0]

        if not data:
            # 如果这里获取失败，通常是因为抖音的风控返回了验证码页面
            print("[ERROR] Failed to extract data dictionary. HTML preview:", html_text[:200])
            raise ValueError("Parse failed: Douyin returned incomplete data (Anti-Crawler triggered).")

        # ==================================================================
        # 提取图片和实况 (Live Photo)
        # ==================================================================
        images = []
        if "images" in data and isinstance(data["images"], list):
            # [调试] 打印第一个图片对象的所有 Key，帮你确认是否有 video 字段
            if len(data["images"]) > 0:
                print(f"[DEBUG] Image Keys found: {list(data['images'][0].keys())}")
                if "video" not in data['images'][0]:
                    print("[WARN] 'video' key missing in image object! Live photo extraction will fail.")

            for img in data["images"]:
                if "url_list" in img and img["url_list"]:
                    image_url = self._get_no_webp_url(img["url_list"])
                    if image_url:
                        live_photo_url = ""
                        
                        # 核心修改：实况视频提取逻辑加强
                        video_obj = img.get("video")
                        if video_obj:
                            # 优先级 1: download_addr (通常质量最好)
                            if "download_addr" in video_obj:
                                ul = video_obj["download_addr"].get("url_list")
                                if ul: live_photo_url = ul[-1]
                            
                            # 优先级 2: play_addr (如果没有 download_addr)
                            if not live_photo_url and "play_addr" in video_obj:
                                ul = video_obj["play_addr"].get("url_list")
                                if ul: live_photo_url = ul[-1]
                                
                            # 优先级 3: bit_rate (深层嵌套)
                            if not live_photo_url and "bit_rate" in video_obj:
                                br = video_obj["bit_rate"]
                                if isinstance(br, list) and len(br) > 0:
                                    pa = br[0].get("play_addr", {})
                                    ul = pa.get("url_list")
                                    if ul: live_photo_url = ul[-1]

                        images.append(
                            ImgInfo(url=image_url, live_photo_url=live_photo_url)
                        )

        # 提取主视频 (如果是纯视频而非图文)
        video_url = ""
        if len(images) == 0:
            if "video" in data and "play_addr" in data["video"]:
                url_list = data["video"]["play_addr"].get("url_list")
                if url_list:
                    video_url = url_list[0].replace("playwm", "play")

        # 获取重定向后的真实 MP4 地址
        video_mp4_url = ""
        if len(video_url) > 0:
            video_mp4_url = await self.get_video_redirect_url(video_url)

        # 封面图
        cover_url = ""
        if "video" in data and "cover" in data["video"]:
            cover_url = self._get_no_webp_url(data["video"]["cover"].get("url_list"))

        return VideoInfo(
            video_url=video_mp4_url,
            cover_url=cover_url,
            title=data.get("desc", ""),
            images=images,
            author=VideoAuthor(
                uid=data.get("author", {}).get("sec_uid", ""),
                name=data.get("author", {}).get("nickname", ""),
                avatar=self._get_no_webp_url(data.get("author", {}).get("avatar_thumb", {}).get("url_list")),
            ),
        )

    async def get_video_redirect_url(self, video_url: str) -> str:
        # 重定向时也带上 Mobile UA
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        }
        async with httpx.AsyncClient(follow_redirects=False, timeout=10.0) as client:
            try:
                response = await client.get(video_url, headers=headers)
                return response.headers.get("location") or video_url
            except:
                return video_url

    async def parse_video_id(self, video_id: str) -> VideoInfo:
        req_url = self._get_request_url_by_video_id(video_id)
        return await self.parse_share_url(req_url)

    def _get_request_url_by_video_id(self, video_id) -> str:
        return f"https://www.iesdouyin.com/share/video/{video_id}/"

    async def _parse_app_share_url(self, share_url: str) -> str:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            response = await client.get(share_url, headers=self.get_default_headers())
        location = response.headers.get("location")
        if not location: return ""
        if "ixigua.com" in location: return ""
        return self._parse_video_id_from_path(location)

    def _parse_video_id_from_path(self, url_path: str) -> str:
        if not url_path: return ""
        try:
            parsed_url = urlparse(url_path)
            query_params = parse_qs(parsed_url.query)
            if "modal_id" in query_params: return query_params["modal_id"][0]
            path = parsed_url.path.strip("/")
            if path:
                path_parts = path.split("/")
                if len(path_parts) > 0: return path_parts[-1]
        except Exception: pass
        return ""

    def _get_no_webp_url(self, url_list: list) -> str:
        if not url_list: return ""
        for url in url_list:
            if url and not url.endswith(".webp"): return url
        return url_list[0] if url_list else ""

    def _is_note_content(self, html_content: str, share_url: str) -> bool:
        return True
