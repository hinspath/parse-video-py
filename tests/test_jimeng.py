import base64
import json

import pytest

from parse_video_py.parser import video_source_info_mapping
from parse_video_py.parser.base import VideoSource
from parse_video_py.parser.jimeng import Jimeng


def _b64_url(url: str) -> str:
    return base64.b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")


def test_jimeng_registered():
    info = video_source_info_mapping[VideoSource.Jimeng]

    assert "jimeng.jianying.com" in info["domain_list"]
    assert info["parser"] is Jimeng


def test_extract_video_qualities_decodes_and_sorts_video_model():
    parser = Jimeng()
    origin_url = "https://v6-default.365yg.com/origin/video/tos/cn/a.mp4?x=1"
    p720_url = "https://v6-default.365yg.com/720/video/tos/cn/a.mp4?x=1"
    public_url = "https://v3-dreamina-de.jianying.com/video/tos/cn/a.mp4?x=1"
    watermark_url = "https://example.com/display_watermark/a.mp4"
    video = {
        "video_url": public_url,
        "video_model": json.dumps(
            {
                "video_list": {
                    "video_4": {
                        "definition": "origin",
                        "main_url": _b64_url(origin_url),
                        "bitrate": 6403338,
                        "vwidth": 720,
                        "vheight": 1254,
                    },
                    "video_3": {
                        "definition": "720p",
                        "main_url": _b64_url(p720_url),
                        "bitrate": 1150312,
                        "vwidth": 720,
                        "vheight": 1254,
                    },
                    "watermark": {
                        "definition": "watermark",
                        "main_url": _b64_url(watermark_url),
                        "bitrate": 9999999,
                    },
                }
            }
        ),
    }

    qualities = parser._extract_video_qualities(video)

    assert [item.url for item in qualities] == [origin_url, p720_url, public_url]
    assert qualities[0].label == "\u539f\u753b"
    assert qualities[-1].label == "\u65e0\u6c34\u5370"


def test_first_video_url_ignores_json_encoded_video_model():
    parser = Jimeng()
    video = {
        "video_model": json.dumps(
            {
                "video_list": {
                    "video_4": {
                        "main_url": _b64_url(
                            "https://v6-default.365yg.com/origin/video/tos/cn/a.mp4"
                        )
                    }
                }
            }
        )
    }

    assert parser._first_video_url(video) == ""


def test_build_video_info_raises_friendly_message_without_resource():
    parser = Jimeng()

    with pytest.raises(ValueError, match="暂未解析到资源"):
        parser._build_video_info({"effect_item_list": [], "dto_list": None})


def test_item_title_prefers_common_title():
    parser = Jimeng()

    assert parser._item_title({"common_attr": {"title": "创意设计"}}) == "创意设计"


def test_item_title_falls_back_to_clean_description():
    parser = Jimeng()

    assert (
        parser._item_title(
            {"common_attr": {"description": "@用户7497855289023 单片树叶雨天跳民族舞"}}
        )
        == "单片树叶雨天跳民族舞"
    )


def test_image_title_prefers_prompt_over_common_title():
    parser = Jimeng()

    data = {
        "common_attr": {"title": "创意设计"},
        "aigc_image_params": {
            "text2image_params": {"prompt": "日系校园摄影，白色衬衫，雨后街角"}
        },
    }

    assert parser._image_title(data) == "日系校园摄影，白色衬衫，雨后街角"


def test_image_title_can_fallback_to_draft_prompt():
    parser = Jimeng()

    data = {
        "aigc_draft": {
            "content": json.dumps(
                {
                    "component_list": [
                        {
                            "abilities": {
                                "generate": {"core_param": {"prompt": "赛博城市夜景"}}
                            }
                        }
                    ]
                },
                ensure_ascii=False,
            )
        }
    }

    assert parser._image_title(data) == "赛博城市夜景"


def test_extract_image_urls_prefers_largest_clean_image_and_dedupes_cdn_hosts():
    parser = Jimeng()
    image_4096 = (
        "https://p11-dreamina-sign.byteimg.com/tos-cn-i-tb4s082cfz/"
        "92e07192928344e49a8b44ebe93d1383"
        "~tplv-tb4s082cfz-aigc_resize:4096:4096.webp?x=1"
    )
    image_1080_same_resource = (
        "https://p26-dreamina-sign.byteimg.com/tos-cn-i-tb4s082cfz/"
        "92e07192928344e49a8b44ebe93d1383"
        "~tplv-tb4s082cfz-aigc_resize:1080:1080.webp?x=1"
    )
    watermarked = (
        "https://p11-dreamina-sign.byteimg.com/tos-cn-i-tb4s082cfz/"
        "92e07192928344e49a8b44ebe93d1383"
        "~tplv-tb4s082cfz-uname_busi_aigc_mark_new.webp?x=1"
    )
    data = {
        "cover_url_map": {
            "1080": image_1080_same_resource,
            "4096": image_4096,
        },
        "image": {
            "large_images": [
                {
                    "width": 1600,
                    "height": 2848,
                    "image_url": watermarked,
                }
            ]
        },
    }

    assert parser._extract_image_urls(data) == [image_4096]
