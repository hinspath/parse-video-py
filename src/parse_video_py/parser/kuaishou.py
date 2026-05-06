import json
import re

import fake_useragent
import httpx

from .base import BaseParser, ImgInfo, VideoAuthor, VideoInfo


class KuaiShou(BaseParser):
    """KuaiShou parser."""

    async def parse_share_url(self, share_url: str) -> VideoInfo:
        user_agent = fake_useragent.UserAgent(os=["ios"]).random
        headers = {
            "User-Agent": user_agent,
            "Referer": "https://v.kuaishou.com/",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        async with httpx.AsyncClient(follow_redirects=False) as client:
            share_response = await client.get(share_url, headers=headers)

        location_url = share_response.headers.get("location", "")
        if not location_url:
            raise Exception("failed to get location url from share url")

        location_url = location_url.replace("/fw/long-video/", "/fw/photo/")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                location_url,
                headers=headers,
                cookies=share_response.cookies,
            )

        re_pattern = r"window\.INIT_STATE\s*=\s*(\{.*?\})\s*</script>"
        re_result = re.search(re_pattern, response.text, flags=re.S)
        if not re_result:
            raise Exception("failed to parse video JSON info from HTML")

        json_data = json.loads(re_result.group(1).strip())
        photo_data = self._find_photo_data(json_data)
        if not photo_data:
            raise Exception("failed to parse photo info from INIT_STATE")

        result_code = photo_data.get("result")
        if result_code != 1:
            raise Exception(f"failed to get photo info: result={result_code}")

        data = photo_data["photo"]
        images = self._get_atlas_images(data)
        cover_urls = data.get("coverUrls") or data.get("webpCoverUrls") or []
        cover_url = self._get_url(cover_urls[0]) if cover_urls else ""
        video_url = self._get_video_url(data)
        if not video_url and not images and cover_url:
            images = [ImgInfo(url=cover_url)]

        return VideoInfo(
            video_url=video_url,
            cover_url=cover_url,
            music_url=self._get_music_url(data),
            title=data.get("caption", ""),
            author=VideoAuthor(
                uid=str(data.get("userId", "")),
                name=data.get("userName", ""),
                avatar=data.get("headUrl", ""),
            ),
            images=images,
        )

    async def parse_video_id(self, video_id: str) -> VideoInfo:
        raise NotImplementedError("KuaiShou does not support direct video ID parsing")

    def _find_photo_data(self, json_data: dict) -> dict:
        for json_item in json_data.values():
            if isinstance(json_item, dict) and "result" in json_item and "photo" in json_item:
                return json_item
        return {}

    def _get_video_url(self, data: dict) -> str:
        for video in data.get("mainMvUrls") or []:
            url = self._get_url(video)
            if url:
                return url
        return ""

    def _get_atlas_images(self, data: dict) -> list[ImgInfo]:
        atlas = (data.get("ext_params") or {}).get("atlas") or {}
        atlas_list = atlas.get("list") or []
        cdn_list = atlas.get("cdn") or atlas.get("cdnList") or atlas.get("cdn_list") or []
        if not atlas_list or not cdn_list:
            return []

        cdn_host = self._get_cdn_host(cdn_list[0])
        if not cdn_host:
            return []

        images = []
        for item in atlas_list:
            if not item:
                continue
            if item.startswith("http"):
                url = item
            elif item.startswith("//"):
                url = f"https:{item}"
            else:
                url = f"https://{cdn_host}{item}"
            images.append(ImgInfo(url=url))
        return images

    def _get_music_url(self, data: dict) -> str:
        music_urls = ((data.get("music") or {}).get("audioUrls") or [])
        for item in music_urls:
            url = self._get_url(item)
            if url:
                return url

        atlas = (data.get("ext_params") or {}).get("atlas") or {}
        music_path = atlas.get("music", "")
        music_cdn_list = atlas.get("musicCdnList") or []
        if music_path and music_cdn_list:
            cdn_host = self._get_cdn_host(music_cdn_list[0])
            if cdn_host:
                return f"https://{cdn_host}{music_path}"

        single = (data.get("ext_params") or {}).get("single") or {}
        music_path = single.get("music", "")
        music_cdn_list = single.get("musicCdnList") or single.get("cdnList") or []
        if music_path and music_cdn_list:
            cdn_host = self._get_cdn_host(music_cdn_list[0])
            if cdn_host:
                return f"https://{cdn_host}{music_path}"

        return ""

    def _get_url(self, value) -> str:
        if isinstance(value, dict):
            return value.get("url", "")
        if isinstance(value, str):
            return value
        return ""

    def _get_cdn_host(self, value) -> str:
        if isinstance(value, dict):
            return value.get("cdn", "")
        if isinstance(value, str):
            return value
        return ""
