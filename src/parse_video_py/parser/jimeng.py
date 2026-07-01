import base64
import hashlib
import json
import re
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .base import BaseParser, ImgInfo, VideoAuthor, VideoInfo, VideoQuality


class Jimeng(BaseParser):
    """JiMeng/Dreamina public share parser."""

    NO_RESOURCE_MESSAGE = (
        "暂未解析到资源，可能是草稿/模板/非公开作品，请公开视频下载后再隐藏。"
    )
    AID = "513695"
    PLATFORM = "7"
    APP_VERSION = "8.4.0"
    WEB_VERSION = "7.5.0"
    DA_VERSION = "3.3.9"
    BASE_URL = "https://jimeng.jianying.com"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
    )
    WATERMARK_RE = re.compile(
        r"watermark|display_watermark|aigc_mark|busi_mark|uname", re.I
    )
    IMAGE_SIZE_RE = re.compile(r"aigc_resize:(\d+):(\d+)", re.I)

    async def parse_share_url(self, share_url: str) -> VideoInfo:
        final_url = await self._resolve_share_url(share_url)
        query = self._parse_query(final_url)
        item_id = query.get("id") or self._extract_id_from_path(final_url)
        if not item_id:
            raise ValueError("failed to parse jimeng item id")

        work_type = (query.get("workDetailType") or "").lower()
        item_type = query.get("itemType") or ""
        if item_type == "9" or work_type == "image":
            return await self.parse_video_id(item_id)

        video_info = await self._parse_mproject_video(item_id, query, final_url)
        if video_info:
            return video_info
        return await self.parse_video_id(item_id)

    async def parse_video_id(self, video_id: str) -> VideoInfo:
        if not video_id:
            raise ValueError("jimeng item id is empty")

        data = {}
        try:
            payload = await self._mweb_post(
                "/mweb/v1/get_item_info",
                {
                    "published_item_id": video_id,
                    "pack_item_opt": self._pack_item_opt(),
                    "item_not_find_detail": True,
                },
            )
            data = payload.get("data") or {}
        except Exception:
            data = {}
        if not data:
            payload = await self._mweb_post(
                "/mweb/v1/mget_item_info",
                {
                    "item_id_list": [video_id],
                    "pack_item_opt": self._pack_item_opt(),
                    "is_dto": True,
                },
            )
            data = self._first_item_from_mget(payload, video_id)

        if not data:
            raise ValueError(self.NO_RESOURCE_MESSAGE)

        if data.get("image") or data.get("cover_url_map"):
            return self._build_image_info(data)
        return self._build_video_info(data)

    async def _parse_mproject_video(
        self, item_id: str, query: dict[str, str], referer: str
    ) -> VideoInfo | None:
        landing = await self._landing_page(query, referer)
        metadata = (
            ((landing.get("data") or {}).get("page_info") or {})
            .get("creation", {})
            .get("metadata", {})
        )
        collection_list = (
            ((landing.get("data") or {}).get("page_info") or {})
            .get("collection_info", {})
            .get("collection_list", [])
        )
        for item in collection_list if isinstance(collection_list, list) else []:
            item_meta = (item.get("creation_info") or {}).get("metadata") or {}
            if str(item_meta.get("video_id") or "") == str(item_id):
                metadata = item_meta
                break

        public_url = self._clean_url(metadata.get("video_url") or "")
        cover_url = self._clean_url(metadata.get("cover_url") or "")
        if public_url and self._is_watermark_url(public_url):
            public_url = ""

        try:
            item_payload = await self._mweb_post(
                "/mweb/v1/get_item_info",
                {
                    "published_item_id": item_id,
                    "pack_item_opt": self._pack_item_opt(),
                    "item_not_find_detail": True,
                },
                referer=referer,
            )
            item_data = item_payload.get("data") or {}
        except Exception:
            item_data = {}

        if item_data:
            info = self._build_video_info(item_data, preferred_url=public_url)
            if cover_url and not info.cover_url:
                info.cover_url = cover_url
            return info

        if not public_url:
            return None
        return VideoInfo(
            video_url=public_url,
            cover_url=cover_url,
            video_urls=[VideoQuality(label="无水印", url=public_url)],
        )

    def _build_video_info(self, data: dict, preferred_url: str = "") -> VideoInfo:
        video = data.get("video") or {}
        common = data.get("common_attr") or {}
        title = self._item_title(data)
        cover_url = self._clean_url(
            video.get("cover_url") or common.get("cover_url") or ""
        )

        qualities = self._extract_video_qualities(video)
        if preferred_url:
            qualities.insert(0, VideoQuality(label="无水印", url=preferred_url))

        qualities = self._dedupe_qualities(qualities)
        video_url = qualities[0].url if qualities else ""
        if not video_url:
            video_url = self._first_video_url(video)
            if video_url:
                qualities.append(VideoQuality(label="无水印", url=video_url))
        if not video_url:
            raise ValueError(self.NO_RESOURCE_MESSAGE)

        author = data.get("author") or {}
        return VideoInfo(
            video_url=video_url,
            cover_url=cover_url,
            title=title,
            author=VideoAuthor(
                uid=str(author.get("user_id") or ""),
                name=author.get("name") or author.get("user_name") or "",
                avatar=author.get("avatar_url") or author.get("avatar") or "",
            ),
            video_urls=qualities,
        )

    def _build_image_info(self, data: dict) -> VideoInfo:
        common = data.get("common_attr") or {}
        title = self._item_title(data)
        image_urls = self._extract_image_urls(data)
        if not image_urls:
            raise ValueError(self.NO_RESOURCE_MESSAGE)

        cover_url = image_urls[0]
        author = data.get("author") or {}
        return VideoInfo(
            video_url="",
            cover_url=cover_url,
            title=title,
            images=[ImgInfo(url=url) for url in image_urls],
            author=VideoAuthor(
                uid=str(author.get("user_id") or ""),
                name=author.get("name") or author.get("user_name") or "",
                avatar=author.get("avatar_url") or author.get("avatar") or "",
            ),
        )

    def _extract_video_qualities(self, video: dict) -> list[VideoQuality]:
        qualities: list[VideoQuality] = []
        model = self._parse_video_model(video.get("video_model"))
        for item in (model.get("video_list") or {}).values():
            if not isinstance(item, dict):
                continue
            url = self._decode_b64_url(item.get("main_url") or "")
            if not url or self._is_watermark_url(url):
                continue
            label = item.get("definition") or item.get("quality") or "视频"
            if label == "origin":
                label = "原画"
            qualities.append(
                VideoQuality(
                    label=str(label),
                    url=url,
                    gear_name=str(
                        item.get("gear_des_key") or item.get("definition") or ""
                    ),
                    quality_type=int(item.get("quality_type") or 0),
                    bit_rate=int(item.get("bitrate") or item.get("real_bitrate") or 0),
                    width=int(item.get("vwidth") or 0),
                    height=int(item.get("vheight") or 0),
                )
            )

        qualities.sort(
            key=lambda item: (item.bit_rate, item.width * item.height), reverse=True
        )
        public_url = self._first_video_url(video)
        if public_url and not self._is_watermark_url(public_url):
            qualities.append(VideoQuality(label="无水印", url=public_url))
        return qualities

    def _extract_image_urls(self, data: dict) -> list[str]:
        candidates: list[tuple[int, str]] = []

        cover_map = data.get("cover_url_map") or {}
        if isinstance(cover_map, dict):
            for size, url in cover_map.items():
                candidates.append(
                    (self._image_rank(str(size), url), self._clean_url(url))
                )

        image = data.get("image") or {}
        for item in image.get("large_images") or []:
            if isinstance(item, dict):
                candidates.append(
                    (
                        int(item.get("width") or 0) * int(item.get("height") or 0),
                        self._clean_url(item.get("image_url") or ""),
                    )
                )

        self._collect_image_candidates(data, candidates)
        good = [
            (rank, url)
            for rank, url in candidates
            if url and not self._is_watermark_url(url) and self._is_image_url(url)
        ]
        good.sort(key=lambda item: item[0], reverse=True)

        urls: list[str] = []
        seen: set[str] = set()
        for _, url in good:
            key = self._image_identity(url)
            if key in seen:
                continue
            seen.add(key)
            urls.append(url)
        return urls

    def _collect_image_candidates(self, value, output: list[tuple[int, str]]) -> None:
        if isinstance(value, dict):
            for item in value.values():
                self._collect_image_candidates(item, output)
        elif isinstance(value, list):
            for item in value:
                self._collect_image_candidates(item, output)
        elif isinstance(value, str) and value.startswith("http"):
            url = self._clean_url(value)
            if self._is_image_url(url):
                output.append((self._image_rank("", url), url))

    async def _resolve_share_url(self, url: str) -> str:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            return str(response.url)

    async def _landing_page(self, query: dict[str, str], referer: str) -> dict:
        url = (
            f"{self.BASE_URL}/luckycat/cn/jianying/campaign/v1/"
            "dreamina/share/landing_page?uid=0&aid=581595&app_name=dreamina"
            "&duanwai_huiliu_page=1"
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                url,
                json={"query_params": query},
                headers={
                    **self._headers(),
                    "Origin": self.BASE_URL,
                    "Referer": referer,
                },
            )
            response.raise_for_status()
            return response.json()

    async def _mweb_post(
        self, uri: str, body: dict, referer: str | None = None, signed: bool = False
    ) -> dict:
        headers = (
            self._signed_headers(uri, referer or self.BASE_URL + "/")
            if signed
            else {
                **self._headers(),
                "Origin": self.BASE_URL,
                "Referer": referer or self.BASE_URL + "/",
            }
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                self._mweb_url(uri), json=body, headers=headers
            )
            response.raise_for_status()
            payload = response.json()

        ret = str(
            payload.get("ret")
            if payload.get("ret") is not None
            else payload.get("err_no", "0")
        )
        if ret not in {"0", "None"}:
            raise ValueError(
                payload.get("errmsg") or payload.get("err_tips") or "jimeng api error"
            )
        return payload

    def _mweb_url(self, uri: str) -> str:
        params = {
            "aid": self.AID,
            "device_platform": "web",
            "region": "cn",
            "webId": str(
                7000000000000000000 + int(time.time() * 1000) % 999999999999999999
            ),
            "da_version": self.DA_VERSION,
            "os": "windows",
            "web_component_open_flag": "1",
            "web_version": self.WEB_VERSION,
            "aigc_features": "app_lip_sync",
        }
        return f"{self.BASE_URL}{uri}?{urlencode(params)}"

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
        }

    def _signed_headers(self, uri: str, referer: str) -> dict[str, str]:
        device_time = str(int(time.time()))
        sign_source = (
            f"9e2c|{uri[-7:]}|{self.PLATFORM}|{self.APP_VERSION}|"
            f"{device_time}||11ac"
        )
        return {
            **self._headers(),
            "Origin": self.BASE_URL,
            "Referer": referer,
            "App-Sdk-Version": "48.0.0",
            "Appid": self.AID,
            "Device-Time": device_time,
            "Lan": "zh-Hans",
            "Loc": "cn",
            "Sign": hashlib.md5(sign_source.encode("utf-8")).hexdigest(),
            "Sign-Ver": "1",
            "Appvr": self.APP_VERSION,
            "Pf": self.PLATFORM,
            "Tdid": "",
        }

    @staticmethod
    def _pack_item_opt() -> dict:
        return {
            "scene": 1,
            "need_data_integrity": True,
            "pack_process_info": 2,
            "need_intention_mark": True,
            "need_follow_info": True,
            "intergen_compress_mode": 1,
        }

    @staticmethod
    def _parse_query(url: str) -> dict[str, str]:
        parsed = urlparse(url)
        return {
            key: values[-1] for key, values in parse_qs(parsed.query).items() if values
        }

    @staticmethod
    def _extract_id_from_path(url: str) -> str:
        match = re.search(r"/(?:work-detail|image|video)/(\d+)", urlparse(url).path)
        return match.group(1) if match else ""

    @staticmethod
    def _first_item_from_mget(payload: dict, item_id: str) -> dict:
        data = payload.get("data") or {}
        for key in ("dto_list", "effect_item_list", "item_list"):
            items = data.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                common = item.get("common_attr") or {}
                if str(common.get("id") or item.get("id") or "") == str(item_id):
                    return item
            if items and isinstance(items[0], dict):
                return items[0]
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _parse_video_model(value) -> dict:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            try:
                return json.loads(value)
            except Exception:
                return {}
        return {}

    @staticmethod
    def _decode_b64_url(value: str) -> str:
        if not value:
            return ""
        try:
            return base64.b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
        except Exception:
            return ""

    @staticmethod
    def _clean_url(value) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip().replace("\\u0026", "&").replace("\\/", "/")

    def _is_watermark_url(self, url: str) -> bool:
        return bool(self.WATERMARK_RE.search(url or ""))

    @staticmethod
    def _is_image_url(url: str) -> bool:
        return bool(re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)|/image", url, re.I))

    @staticmethod
    def _is_video_url(url: str) -> bool:
        return bool(re.search(r"\.(?:mp4|mov|m3u8)(?:\?|$)|/video/", url, re.I))

    def _first_video_url(self, value) -> str:
        if isinstance(value, dict):
            for key in ("video_url", "download_url", "play_url", "url"):
                url = self._clean_url(value.get(key))
                if url and self._is_video_url(url) and not self._is_watermark_url(url):
                    return url
            for item in value.values():
                found = self._first_video_url(item)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self._first_video_url(item)
                if found:
                    return found
        elif isinstance(value, str):
            url = self._clean_url(value)
            if (
                url.startswith("http")
                and self._is_video_url(url)
                and not self._is_watermark_url(url)
            ):
                return url
        return ""

    def _image_rank(self, size_text: str, url: str) -> int:
        if size_text.isdigit():
            size = int(size_text)
            return size * size
        match = self.IMAGE_SIZE_RE.search(url or "")
        if match:
            return int(match.group(1)) * int(match.group(2))
        return 0

    @staticmethod
    def _image_identity(url: str) -> str:
        parsed = urlparse(url)
        return (parsed.path or url).split("~", 1)[0]

    def _item_title(self, data: dict) -> str:
        common = data.get("common_attr") or {}
        for key in ("title", "name", "description"):
            title = self._clean_title(common.get(key) or "")
            if title:
                return title
        return self._clean_title(self._prompt_title(data))

    @staticmethod
    def _clean_title(value: str) -> str:
        if not isinstance(value, str):
            return ""
        title = re.sub(r"\s+", " ", value).strip()
        title = re.sub(r"^@[\w\-\u4e00-\u9fff]+\s+", "", title)
        return title

    @staticmethod
    def _prompt_title(data: dict) -> str:
        description = data.get("description") or {}
        prompts = description.get("prompt") or []
        text_parts = [
            str(item.get("text") or "")
            for item in prompts
            if isinstance(item, dict) and item.get("text")
        ]
        if text_parts:
            return " ".join(text_parts)
        return ""

    @staticmethod
    def _dedupe_qualities(qualities: list[VideoQuality]) -> list[VideoQuality]:
        result: list[VideoQuality] = []
        seen: set[str] = set()
        for item in qualities:
            if not item.url or item.url in seen:
                continue
            seen.add(item.url)
            result.append(item)
        return result
