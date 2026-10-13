import re

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

        # 视频地址
        h264_data = (
            data.get("video", {}).get("media", {}).get("stream", {}).get("h264", [])
            or []
        )
        video_qualities = self._video_qualities(h264_data)
        video_url = video_qualities[0].url if video_qualities else ""
        duration = 0
        if video_url:
            stream = next(
                (
                    item
                    for item in h264_data
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
            seen.add(url)
            width = cls._positive_int(stream.get("width"))
            height = cls._positive_int(stream.get("height"))
            resolution = min(width, height) if width and height else width or height
            label = (
                f"{resolution}P"
                if resolution
                else str(stream.get("qualityType") or "默认")
            )
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
                )
            )
        qualities.sort(
            key=lambda item: (
                (
                    min(item.width, item.height)
                    if item.width and item.height
                    else item.width or item.height
                ),
                item.bit_rate,
            ),
            reverse=True,
        )
        return qualities

    async def parse_video_id(self, video_id: str) -> VideoInfo:
        raise NotImplementedError("小红书暂不支持直接解析视频ID")
