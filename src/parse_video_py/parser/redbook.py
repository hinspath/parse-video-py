import re
from collections import Counter
from urllib.parse import urlparse

import httpx
import yaml

from .base import BaseParser, ImgInfo, VideoAuthor, VideoInfo, VideoQuality


class RedBook(BaseParser):
    """
    小红书
    """

    _USER_AGENTS = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) "
        "Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
        "Gecko/20100101 Firefox/124.0",
    )
    _MOBILE_USER_AGENT = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
        "Mobile/15E148 Safari/604.1"
    )

    async def parse_share_url(self, share_url: str) -> VideoInfo:
        pattern = re.compile(
            pattern=r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>",
            flags=re.DOTALL,
        )
        last_error = "小红书暂未返回笔记内容，请稍后重试或重新分享链接"
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for user_agent in self._USER_AGENTS:
                # Retry from the share URL without cookies set by a blocked page.
                client.cookies.clear()
                response = await client.get(
                    share_url, headers={"User-Agent": user_agent}
                )
                if response.status_code in (401, 403, 429):
                    last_error = "小红书暂时限制了访问，请稍后重试"
                    continue
                response.raise_for_status()
                if response.url.path.rstrip("/") == "/login":
                    last_error = "小红书要求登录后查看该笔记，请稍后重试或重新分享链接"
                    continue

                find_res = pattern.search(response.text)
                if not find_res or not find_res.group(1):
                    last_error = "未能获取小红书笔记数据，请稍后重试或重新分享链接"
                    continue
                try:
                    json_data = yaml.safe_load(find_res.group(1))
                except yaml.YAMLError:
                    last_error = "小红书返回的笔记数据格式异常，请稍后重试"
                    continue
                note_state = (
                    json_data.get("note") if isinstance(json_data, dict) else None
                )
                if not isinstance(note_state, dict):
                    continue
                note_id = note_state.get("currentNoteId")
                if note_id == "undefined":
                    raise ValueError("小红书分享链接已失效，请在小红书重新复制分享链接")
                detail_map = note_state.get("noteDetailMap")
                if not note_id or not isinstance(detail_map, dict):
                    continue
                detail = detail_map.get(note_id)
                data = detail.get("note") if isinstance(detail, dict) else None
                if isinstance(data, dict) and data:
                    break
            else:
                raise ValueError(last_error)

            video_streams = [
                stream
                for stream in (
                    data.get("video", {}).get("media", {}).get("stream", {}).get("h264")
                    or []
                )
                if isinstance(stream, dict)
            ]
            # The mobile page can expose smaller streams absent from the desktop page.
            if any(
                self._positive_int(stream.get("size")) > 200 * 1024 * 1024
                for stream in video_streams
            ) or any(self._is_watermarked_stream(stream) for stream in video_streams):
                video_streams.extend(
                    await self._mobile_video_streams(
                        client, share_url, note_id, pattern
                    )
                )

        # 视频地址
        video_qualities = self._video_qualities(video_streams)
        if data.get("type") == "video" and not video_qualities:
            raise ValueError(
                "暂未获取到小红书无平台水印的视频资源，请稍后重试或重新分享链接"
            )
        video_url = video_qualities[0].url if video_qualities else ""
        duration = 0
        if video_url:
            stream = next(
                (
                    item
                    for item in video_streams
                    if isinstance(item, dict) and item.get("masterUrl") == video_url
                ),
                {},
            )
            duration = (
                self._positive_int(
                    stream.get("duration") or stream.get("videoDuration")
                )
                or self._positive_int(
                    data.get("video", {}).get("capa", {}).get("duration")
                )
                * 1000
            )

        # 获取图集图片地址
        images = []
        if len(video_url) <= 0:
            for img_item in data["imageList"]:
                # 个别图片有水印, 替换图片域名
                image_id = img_item["urlDefault"].split("/")[-1].split("!")[0]
                # 如果链接中带有 spectrum/ , 替换域名时需要带上
                spectrum_str = (
                    "spectrum/" if "spectrum" in img_item["urlDefault"] else ""
                )
                new_url = (
                    "https://ci.xiaohongshu.com/notes_pre_post/"
                    + f"{spectrum_str}{image_id}"
                    + "?imageView2/format/jpg"
                )
                img_info = ImgInfo(url=new_url)
                # 如果原图片网址中没有 notes_pre_post 关键字，不支持替换域名，使用原域名
                if "notes_pre_post" not in img_item["urlDefault"]:
                    new_url = img_item["urlDefault"]
                    img_info.url = img_item["urlDefault"]
                # 是否有 livephoto 视频地址
                if img_item.get("livePhoto", False) and (
                    h264_data := img_item.get("stream", {}).get("h264", [])
                ):
                    img_info.live_photo_url = h264_data[0]["masterUrl"]
                images.append(img_info)

        video_info = VideoInfo(
            video_url=video_url,
            cover_url=data["imageList"][0]["urlDefault"],
            title=data["title"],
            images=images,
            video_urls=video_qualities,
            duration=duration,
            size=video_qualities[0].size if video_qualities else 0,
            author=VideoAuthor(
                uid=data["user"]["userId"],
                name=data["user"]["nickname"],
                avatar=data["user"]["avatar"],
            ),
        )
        return video_info

    async def _mobile_video_streams(
        self,
        client: httpx.AsyncClient,
        share_url: str,
        note_id: str,
        pattern: re.Pattern,
    ) -> list[dict]:
        try:
            client.cookies.clear()
            response = await client.get(
                share_url, headers={"User-Agent": self._MOBILE_USER_AGENT}
            )
            response.raise_for_status()
            match = pattern.search(response.text)
            if not match:
                return []
            state = yaml.safe_load(match.group(1))
        except (httpx.HTTPError, yaml.YAMLError):
            return []
        if not isinstance(state, dict):
            return []
        store = state.get("noteData")
        payload = store.get("data") if isinstance(store, dict) else None
        note = payload.get("noteData") if isinstance(payload, dict) else None
        if not isinstance(note, dict) or note.get("noteId") != note_id:
            return []
        video = note.get("video")
        media = video.get("media") if isinstance(video, dict) else None
        streams = media.get("stream") if isinstance(media, dict) else None
        if not isinstance(streams, dict):
            return []
        result = []
        for codec in ("h264", "h265"):
            entries = streams.get(codec)
            if not isinstance(entries, list):
                continue
            result.extend(
                {**stream, "videoCodec": stream.get("videoCodec") or codec}
                for stream in entries
                if isinstance(stream, dict)
            )
        return result

    @classmethod
    def _is_watermarked_stream(cls, stream: dict) -> bool:
        stream_type = cls._positive_int(
            stream.get("streamType") or stream.get("stream_type")
        )
        description = str(
            stream.get("streamDesc") or stream.get("stream_desc") or ""
        ).upper()
        url = stream.get("masterUrl")
        path = urlparse(url if isinstance(url, str) else "").path
        # MINI_APP_259 burns the platform logo and author into the video frames.
        return (
            stream_type == 259
            or description.startswith("MINI_APP")
            or "/259/" in path
            or path.endswith("_259.mp4")
        )

    @staticmethod
    def _positive_int(value) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError, OverflowError):
            return 0

    @classmethod
    def _video_qualities(cls, streams: list) -> list[VideoQuality]:
        qualities = []
        seen = set()
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            url = stream.get("masterUrl")
            if not isinstance(url, str) or not url or url in seen:
                continue
            if cls._is_watermarked_stream(stream):
                continue
            codec = str(stream.get("videoCodec") or "h264").lower()
            if codec == "hevc":
                codec = "h265"
            if codec not in {"h264", "h265"}:
                continue
            seen.add(url)
            width = cls._positive_int(stream.get("width"))
            height = cls._positive_int(stream.get("height"))
            resolution = min(width, height) if width and height else width or height
            label = (
                f"{resolution}P"
                if resolution
                else str(stream.get("qualityType") or "默认")
            )
            if codec == "h265":
                label += " · H.265"
            qualities.append(
                VideoQuality(
                    label=label,
                    url=url,
                    gear_name=str(stream.get("qualityType") or ""),
                    bit_rate=cls._positive_int(
                        stream.get("avgBitrate") or stream.get("videoBitrate")
                    ),
                    width=width,
                    height=height,
                    size=cls._positive_int(stream.get("size")),
                    codec=codec,
                )
            )
        qualities.sort(
            key=lambda item: (
                item.codec == "h264",
                (
                    min(item.width, item.height)
                    if item.width and item.height
                    else item.width or item.height
                ),
                item.bit_rate,
            ),
            reverse=True,
        )
        labels = Counter(item.label for item in qualities)
        for quality in qualities:
            if labels[quality.label] > 1 and quality.bit_rate:
                quality.label += f" · {round(quality.bit_rate / 1000)}kbps"
        return qualities

    async def parse_video_id(self, video_id: str) -> VideoInfo:
        raise NotImplementedError("小红书暂不支持直接解析视频ID")
