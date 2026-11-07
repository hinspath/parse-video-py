import json
from unittest.mock import AsyncMock

import httpx
import pytest

from parse_video_py.parser.base import ImgInfo, VideoInfo, VideoQuality
from parse_video_py.parser.douyin import DouYin


def test_live_photo_url_prefers_last_url_and_removes_watermark():
    parser = DouYin()
    image_info = {
        "video": {
            "play_addr": {
                "url_list": [
                    "https://example.com/playwm/low.mp4",
                    "https://example.com/playwm/high.mp4",
                ]
            }
        }
    }

    assert parser._get_live_photo_url(image_info) == "https://example.com/play/high.mp4"


def test_live_photo_url_finds_nested_video_url():
    parser = DouYin()
    image_info = {
        "url_list": ["https://example.com/image.jpg"],
        "video": {
            "bit_rate": [
                {
                    "play_addr": {
                        "url_list": [
                            "https://example.com/live/playwm/?video_id=abc123"
                        ]
                    }
                }
            ]
        },
    }

    assert (
        parser._get_live_photo_url(image_info)
        == "https://example.com/live/play/?video_id=abc123"
    )


def test_extract_signature_from_execjs_error_output():
    parser = DouYin()
    err_text = """(-6, '\n["ok","dJWhQRLDDE2PhD6f51/LfY3q6IN3Y8y30trEMD2fFdfZd639HMT09exoRpzvjUmjE4/0IeYjy4hbT3ohrQ2y8qwf9W0L/25gsDSkKl12so0j53inCLf/E0iE5hsAtFH8svr4iKi8owICSYyhldAJ5kIlO62-zo0/9IL="]\n', '')"""

    assert parser._extract_signature_from_text(err_text).startswith("dJWhQR")


def test_aweme_detail_api_shape_preserves_live_photo_data():
    parser = DouYin()
    detail = {
        "desc": "测试图集",
        "images": [
            {
                "url_list": [
                    "https://example.com/cover.webp",
                    "https://example.com/image.jpg",
                ],
                "video": {
                    "download_addr": {
                        "url_list": ["https://example.com/playwm/live.mp4"]
                    }
                },
            }
        ],
        "video": {
            "play_addr": {"uri": "music-uri"},
            "cover": {"url_list": ["https://example.com/cover.jpg"]},
        },
        "author": {
            "sec_uid": "uid",
            "nickname": "作者",
            "avatar_thumb": {"url_list": ["https://example.com/avatar.jpg"]},
        },
    }

    result = parser._video_info_from_aweme_detail(detail)

    assert result.video_url == ""
    assert result.music_url == "music-uri"
    assert result.title == "测试图集"
    assert result.images == [
        ImgInfo(
            url="https://example.com/image.jpg",
            live_photo_url="https://example.com/play/live.mp4",
        )
    ]
    assert result.author.name == "作者"


def test_aweme_detail_video_preserves_quality_options():
    parser = DouYin()
    detail = {
        "desc": "测试视频",
        "video": {
            "play_addr": {
                "url_list": ["https://example.com/playwm/default.mp4"]
            },
            "bit_rate": [
                {
                    "gear_name": "normal_1080_0",
                    "quality_type": 1,
                    "bit_rate": 668308,
                    "play_addr": {
                        "url_list": [
                            "https://example.com/playwm/1080-a.mp4",
                            "https://example.com/playwm/1080-b.mp4",
                        ]
                    },
                },
                {
                    "gear_name": "normal_540_0",
                    "quality_type": 20,
                    "bit_rate": 617941,
                    "play_addr": {
                        "url_list": ["https://example.com/playwm/540.mp4"]
                    },
                },
                {
                    "gear_name": "normal_720_0",
                    "quality_type": 10,
                    "bit_rate": 548868,
                    "play_addr": {
                        "url_list": ["https://example.com/playwm/720.mp4"]
                    },
                },
                {
                    "gear_name": "720_4_1",
                    "quality_type": 14,
                    "bit_rate": 224820,
                    "play_addr": {
                        "url_list": ["https://example.com/playwm/720-low.mp4"]
                    },
                },
            ],
        },
    }

    result = parser._video_info_from_aweme_detail(detail)

    assert result.video_url == "https://example.com/play/1080-b.mp4"
    assert result.video_urls == [
        VideoQuality(
            label="1080P · 668kbps",
            url="https://example.com/play/1080-b.mp4",
            gear_name="normal_1080_0",
            quality_type=1,
            bit_rate=668308,
            height=1080,
        ),
        VideoQuality(
            label="720P · 549kbps",
            url="https://example.com/play/720.mp4",
            gear_name="normal_720_0",
            quality_type=10,
            bit_rate=548868,
            height=720,
        ),
        VideoQuality(
            label="540P · 618kbps",
            url="https://example.com/play/540.mp4",
            gear_name="normal_540_0",
            quality_type=20,
            bit_rate=617941,
            height=540,
        ),
    ]


def test_aweme_detail_image_post_info_preserves_live_photo_data():
    parser = DouYin()
    detail = {
        "desc": "实况图集",
        "image_post_info": {
            "images": [
                {
                    "display_image": {
                        "url_list": [
                            "https://example.com/display.webp",
                            "https://example.com/display.jpg",
                        ]
                    },
                    "video": {
                        "play_addr": {
                            "url_list": ["https://example.com/playwm/live.mp4"]
                        }
                    },
                }
            ]
        },
        "video": {"cover": {"url_list": ["https://example.com/cover.jpg"]}},
        "author": {"nickname": "作者"},
    }

    result = parser._video_info_from_aweme_detail(detail)

    assert result.images == [
        ImgInfo(
            url="https://example.com/display.jpg",
            live_photo_url="https://example.com/play/live.mp4",
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("request_cookie", ["", "user-cookie"])
async def test_cookie_api_remains_first_and_keeps_request_cookie_priority(
    monkeypatch, request_cookie
):
    monkeypatch.setattr(
        "parse_video_py.parser.douyin.GLOBAL_DY_COOKIE", "global-cookie"
    )
    parser = DouYin()
    expected = VideoInfo(video_url="https://example.com/video.mp4", cover_url="")
    detail_api = AsyncMock(return_value=expected)
    slides_api = AsyncMock(side_effect=AssertionError("Cookie API must stay first"))
    monkeypatch.setattr(parser, "_parse_with_aweme_detail_api", detail_api)
    monkeypatch.setattr(parser, "_get_slides_info", slides_api)
    token = parser.set_request_cookie(request_cookie)
    try:
        assert (
            await parser.parse_share_url("https://www.douyin.com/video/123") is expected
        )
    finally:
        parser.reset_request_cookie(token)
    detail_api.assert_awaited_once_with("123", request_cookie or "global-cookie")
    slides_api.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("live_photo", [False, True])
async def test_failed_cookie_api_uses_share_api_and_preserves_media(
    monkeypatch, live_photo
):
    parser = DouYin()
    monkeypatch.setattr(parser, "_get_active_cookie", lambda: "existing-cookie")
    monkeypatch.setattr(
        parser,
        "_parse_with_aweme_detail_api",
        AsyncMock(side_effect=ValueError("blocked")),
    )
    detail = {
        "desc": "Share API result",
        "video": {
            "play_addr": {"url_list": ["https://example.com/playwm/video.mp4"]},
            "cover": {"url_list": ["https://example.com/cover.jpg"]},
            "bit_rate": [
                {
                    "gear_name": "normal_720_0",
                    "bit_rate": 1000000,
                    "play_addr": {"url_list": ["https://example.com/playwm/720.mp4"]},
                }
            ],
        },
    }
    if live_photo:
        detail["images"] = [
            {
                "url_list": ["https://example.com/photo.jpg"],
                "video": {
                    "play_addr": {
                        "url_list": [
                            "https://example.com/playwm/live-low.mp4",
                            "https://example.com/playwm/live-high.mp4",
                        ]
                    }
                },
            }
        ]
    slides_api = AsyncMock(return_value={"aweme_details": [detail]})
    redirect = AsyncMock(side_effect=lambda url: url)
    monkeypatch.setattr(parser, "_get_slides_info", slides_api)
    monkeypatch.setattr(parser, "get_video_redirect_url", redirect)

    info = await parser.parse_share_url("https://www.douyin.com/video/123")

    slides_api.assert_awaited_once_with("123")
    assert info.title == "Share API result"
    if live_photo:
        assert info.video_url == ""
        assert info.images == [
            ImgInfo(
                url="https://example.com/photo.jpg",
                live_photo_url="https://example.com/play/live-high.mp4",
            )
        ]
        redirect.assert_not_awaited()
    else:
        assert info.video_url == "https://example.com/play/720.mp4"
        assert info.video_urls[0].height == 720
        assert info.video_urls[0].bit_rate == 1000000
        redirect.assert_awaited_once_with(info.video_url)


@pytest.mark.asyncio
@pytest.mark.parametrize("note", [False, True])
async def test_share_api_uses_video_then_note_parameters(monkeypatch, note):
    requests = []
    expected = {"aweme_details": [{"desc": "test"}]}

    def handler(request):
        requests.append(request)
        assert request.url.path == "/web/api/v2/aweme/slidesinfo/"
        assert request.url.params["aweme_ids"] == "[123]"
        if note and "request_source" not in request.url.params:
            return httpx.Response(200, json={"aweme_details": []})
        return httpx.Response(200, json=expected)

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "parse_video_py.parser.douyin.httpx.AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert await DouYin()._get_slides_info("123") == expected
    assert dict(requests[0].url.params) == {"aweme_ids": "[123]"}
    assert len(requests) == (2 if note else 1)
    if note:
        assert dict(requests[1].url.params) == {
            "aweme_ids": "[123]",
            "request_source": "200",
        }


@pytest.mark.asyncio
async def test_missing_video_info_has_friendly_error(monkeypatch):
    parser = DouYin()
    monkeypatch.setattr(parser, "_get_active_cookie", lambda: "")
    monkeypatch.setattr(parser, "_get_slides_info", AsyncMock(return_value=None))
    state = {"loaderData": {"video_(id)/page": {"isSSR": False}}}
    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "parse_video_py.parser.douyin.httpx.AsyncClient",
        lambda **kwargs: async_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    text="<script>window._ROUTER_DATA="
                    + json.dumps(state)
                    + "</script>",
                )
            ),
            **kwargs,
        ),
    )
    with pytest.raises(ValueError, match="抖音暂未返回作品数据"):
        await parser.parse_share_url("https://www.douyin.com/video/123")
