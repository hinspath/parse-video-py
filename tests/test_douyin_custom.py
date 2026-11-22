import json
from unittest.mock import AsyncMock

import httpx
import pytest

from parse_video_py.parser.base import ImgInfo, VideoInfo, VideoQuality
from parse_video_py.parser.douyin import DouYin, DouYinWorkUnavailable
from parse_video_py.parser.douyin_live_page import _live_urls_from_frames


def _desktop_frame(work_id, images):
    props = {
        "awemeId": work_id,
        "aweme": {"statusCode": 0, "detail": {"images": images}},
    }
    record = "7:" + json.dumps(["$", "$L9", None, props])
    return f"self.__pace_f.push({json.dumps([1, record])});"


def test_desktop_live_frame_uses_only_matching_work_and_unique_live_images():
    clip = "https://v26-web.douyinvod.com/a/clip.mp4"
    video = {"playAddr": [{"src": clip}]}
    good = {"uri": "live", "clipType": 5, "video": video}
    frame = _desktop_frame("123", [
        good,
        {"uri": "still", "clipType": 2, "video": video},
        {"uri": "duplicated", "clipType": 3, "video": video},
        {"uri": "duplicated", "clipType": 2},
        {"uri": "audio", "clipType": 5, "video": {
            "playAddr": [{"src": "https://lf9-music-east.douyinstatic.com/audio"}]
        }},
        {"uri": "not-a-cdn", "clipType": 5, "video": {
            "playAddr": [{"src": "https://douyinvod.com.example/clip.mp4"}]
        }},
    ])
    assert _live_urls_from_frames(
        [_desktop_frame("999", [good]), "self.__pace_f.push(bad)", frame], "123"
    ) == {"live": clip}


@pytest.mark.asyncio
async def test_share_fallback_fills_only_missing_live_by_image_uri(monkeypatch):
    parser = DouYin()
    monkeypatch.setattr(parser, "_get_active_cookie", lambda: "")
    original = "https://media.example/old.mp4"
    extra = "https://v26-web.douyinvod.com/new.mp4"
    images = [
        {"uri": "still", "url_list": ["https://media.example/still.jpg"]},
        {"uri": "live", "url_list": ["https://media.example/live.jpg"]},
        {"uri": "working", "url_list": ["https://media.example/working.jpg"],
         "video": {"play_addr": {"url_list": [original]}}},
    ]
    monkeypatch.setattr(parser, "_get_slides_info", AsyncMock(return_value={
        "aweme_details": [{"images": images}],
    }))
    browser_fallback = AsyncMock(return_value={
        "working": "https://v26-web.douyinvod.com/should-not-overwrite.mp4",
        "live": extra,
    })
    monkeypatch.setattr(
        "parse_video_py.parser.douyin.get_desktop_live_urls", browser_fallback,
    )

    info = await parser.parse_share_url("https://www.iesdouyin.com/share/slides/123/")

    browser_fallback.assert_awaited_once_with("123")
    assert [image.url for image in info.images] == [row["url_list"][0] for row in images]
    assert [image.live_photo_url for image in info.images] == ["", extra, original]


@pytest.mark.asyncio
async def test_complete_live_gallery_does_not_open_browser(monkeypatch):
    parser = DouYin()
    monkeypatch.setattr(parser, "_get_active_cookie", lambda: "")
    monkeypatch.setattr(parser, "_get_slides_info", AsyncMock(return_value={
        "aweme_details": [{"images": [{
            "uri": "live",
            "url_list": ["https://media.example/live.jpg"],
            "video": {"play_addr": {"url_list": ["https://media.example/a.mp4"]}},
        }]}],
    }))
    browser_fallback = AsyncMock()
    monkeypatch.setattr(
        "parse_video_py.parser.douyin.get_desktop_live_urls", browser_fallback,
    )

    info = await parser.parse_share_url("https://www.iesdouyin.com/share/slides/123/")

    browser_fallback.assert_not_awaited()
    assert info.images[0].live_photo_url == "https://media.example/a.mp4"


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
    with pytest.raises(DouYinWorkUnavailable, match="抖音暂未返回作品数据"):
        await parser.parse_share_url("https://www.douyin.com/video/123")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,count,live",
    [("note", 1, False), ("note", 3, False), ("note", 1, True), ("slides", 3, True)],
)
async def test_image_share_fallback_preserves_redirect_and_media(
    monkeypatch, kind, count, live
):
    parser = DouYin()
    monkeypatch.setattr(parser, "_get_active_cookie", lambda: "")
    monkeypatch.setattr(parser, "_get_slides_info", AsyncMock(return_value=None))
    location = f"https://www.iesdouyin.com/share/{kind}/123/?share_sign=x%2Fy&from=app"
    media = []
    for index in range(count):
        image = {"display_image": {"url_list": [f"https://image.example/{index}.jpg"]}}
        if live:
            image["video"] = {"play_addr": {
                "url_list": [f"https://media.example/playwm/{index}.mp4", None, ""]
            }}
        media.append(image)
    work = {
        "image_post_info": {"images": media},
        "video": {"play_addr": {"url_list": [], "uri": "sound"}},
    }
    requests = []

    def handle(request):
        url = str(request.url)
        requests.append(url)
        if url == "https://v.douyin.com/sample/":
            return httpx.Response(302, headers={"Location": location})
        assert url == location
        state = {"loaderData": {
            "video_(id)/page": {"isSSR": False},
            f"{kind}_(id)/page": {"videoInfoRes": {"item_list": [work]}},
        }}
        return httpx.Response(
            200, text=f"<script>window._ROUTER_DATA={json.dumps(state)};</script>"
        )

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "parse_video_py.parser.douyin.httpx.AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    info = await parser.parse_share_url("https://v.douyin.com/sample/")
    assert requests == ["https://v.douyin.com/sample/", location]
    assert info.video_url == ""
    assert info.images == [
        ImgInfo(
            url=f"https://image.example/{index}.jpg",
            live_photo_url=f"https://media.example/play/{index}.mp4" if live else "",
        )
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_image_share_ignores_signed_placeholder_and_reads_share_api(monkeypatch):
    parser = DouYin()
    monkeypatch.setattr(parser, "_get_active_cookie", lambda: "test-cookie")
    signed = AsyncMock(return_value=VideoInfo(video_url="placeholder", cover_url=""))
    monkeypatch.setattr(parser, "_parse_with_aweme_detail_api", signed)
    gallery = {
        "aweme_details": [{"image_infos": [{"url_list": ["https://image.example/a.jpg"]}]}]
    }
    shared = AsyncMock(side_effect=[gallery, {"aweme_details": [{"desc": "no images"}]}])
    monkeypatch.setattr(parser, "_get_slides_info", shared)
    read_page = AsyncMock(return_value=None)
    monkeypatch.setattr(parser, "_read_share_page", read_page)

    result = await parser.parse_share_url("https://www.douyin.com/note/123")
    signed.assert_awaited_once_with("123", "test-cookie")
    read_page.assert_not_awaited()
    assert result.images == [ImgInfo(url="https://image.example/a.jpg")]
    assert result.video_url == ""
    with pytest.raises(DouYinWorkUnavailable):
        await parser.parse_share_url("https://www.douyin.com/note/123")
    assert read_page.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["note", "video"])
async def test_public_share_retry_carries_only_per_request_guest_cookie(monkeypatch, kind):
    parser = DouYin()
    monkeypatch.setattr(parser, "_get_active_cookie", lambda: "sessionid=test-account")
    monkeypatch.setattr(
        parser, "_parse_with_aweme_detail_api",
        AsyncMock(return_value=VideoInfo(video_url="", cover_url="")),
    )
    slides = AsyncMock(return_value=None)
    monkeypatch.setattr(parser, "_get_slides_info", slides)
    requests = []

    def handle(request):
        requests.append((request.url.path, request.headers.get("cookie")))
        if not request.headers.get("cookie"):
            assert request.url.path == f"/share/{kind}/123/"
            return httpx.Response(
                200, text="<html>No work yet</html>",
                headers={"Set-Cookie": "visitor=test-guest; Path=/; Secure"},
            )
        assert request.headers["cookie"] == "visitor=test-guest"
        assert request.url.path == "/share/video/123/"
        work = {"aweme_id": "123"}
        if kind == "note":
            work["images"] = [{"url_list": ["https://image.example/a.jpg"]}]
        else:
            work["video"] = {"play_addr": {"url_list": ["https://media.example/a.mp4"]}}
        state = {"loaderData": {"video_(id)/page": {"videoInfoRes": {"item_list": [work]}}}}
        return httpx.Response(
            200, text=f"<script>window._ROUTER_DATA={json.dumps(state)};</script>"
        )

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "parse_video_py.parser.douyin.httpx.AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    monkeypatch.setattr(parser, "get_video_redirect_url", AsyncMock(side_effect=lambda url: url))
    for _ in range(2):
        info = await parser.parse_share_url(f"https://www.douyin.com/{kind}/123")
        if kind == "note":
            assert info.images == [ImgInfo(url="https://image.example/a.jpg")]
        else:
            assert info.video_url == "https://media.example/a.mp4"

    assert requests == [(f"/share/{kind}/123/", None), ("/share/video/123/", "visitor=test-guest")] * 2
    assert slides.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,expected_requests", [("note", 2), ("video", 1)])
async def test_public_share_retry_is_bounded_without_guest_cookie(
    monkeypatch, kind, expected_requests
):
    parser = DouYin()
    monkeypatch.setattr(parser, "_get_active_cookie", lambda: "")
    monkeypatch.setattr(parser, "_get_slides_info", AsyncMock(return_value=None))
    requests = []

    def handle(request):
        requests.append(request)
        assert "cookie" not in request.headers
        return httpx.Response(200, text="<html>No media</html>")

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "parse_video_py.parser.douyin.httpx.AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    with pytest.raises(DouYinWorkUnavailable):
        await parser.parse_share_url(f"https://www.douyin.com/{kind}/123")
    assert len(requests) == expected_requests


@pytest.mark.asyncio
async def test_late_guest_cookie_can_recover_single_photo_without_live_video(monkeypatch):
    parser = DouYin()
    monkeypatch.setattr(parser, "_get_active_cookie", lambda: "")
    monkeypatch.setattr(parser, "_get_slides_info", AsyncMock(return_value=None))
    requests = []

    def handle(request):
        requests.append((request.url.path, request.headers.get("cookie")))
        if request.url.path == "/share/note/123/":
            return httpx.Response(200, text="<html>No detail or cookie</html>")
        if not request.headers.get("cookie"):
            return httpx.Response(
                200, text="<html>No detail yet</html>",
                headers={"Set-Cookie": "visitor=late-guest; Path=/; Secure"},
            )
        work = {
            "aweme_id": "123",
            "images": [{"url_list": ["https://image.example/cover.jpg"]}],
            "video": {"play_addr": {"uri": "audio", "url_list": ["https://media.example/audio"]}},
        }
        state = {"loaderData": {"video_(id)/page": {"videoInfoRes": {"item_list": [work]}}}}
        return httpx.Response(
            200, text=f"<script>window._ROUTER_DATA={json.dumps(state)};</script>"
        )

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "parse_video_py.parser.douyin.httpx.AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    info = await parser.parse_share_url("https://www.douyin.com/note/123")
    assert info.images == [ImgInfo(url="https://image.example/cover.jpg", live_photo_url="")]
    assert info.video_url == ""
    assert requests == [
        ("/share/note/123/", None),
        ("/share/video/123/", None),
        ("/share/video/123/", "visitor=late-guest"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429])
async def test_public_share_does_not_retry_explicit_denials(monkeypatch, status):
    parser = DouYin()
    monkeypatch.setattr(parser, "_get_active_cookie", lambda: "")
    monkeypatch.setattr(parser, "_get_slides_info", AsyncMock(return_value=None))
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status)

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "parse_video_py.parser.douyin.httpx.AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await parser.parse_share_url("https://www.douyin.com/note/123")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_shortlink_does_not_request_an_unrelated_redirect_host(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request.url.host)
        return httpx.Response(
            302, headers={"Location": "https://elsewhere.example/note/123/"}
        )

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "parse_video_py.parser.douyin.httpx.AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    with pytest.raises(ValueError, match="Failed to resolve"):
        await DouYin().parse_share_url("https://v.douyin.com/sample/")
    assert requests == ["v.douyin.com"]
