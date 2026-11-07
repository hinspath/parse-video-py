from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from parse_video_py import web
from parse_video_py.web import _download_request_headers


@pytest.mark.parametrize(
    "host",
    [
        "upos-sz-mirrorcos.bilivideo.com",
        "upos-sz-mirrorcos.bilivideo.cn",
        "upos-hz-mirrorakam.akamaized.net",
        "upos-sz-mirrorcos.bilivideo.com:443",
    ],
)
def test_bilibili_media_uses_required_referer(host):
    headers = _download_request_headers(f"https://{host}/video.mp4?sign=example")
    assert headers["Referer"] == "https://www.bilibili.com/"
    assert "Range" not in headers


@pytest.mark.parametrize(
    "url,referer",
    [
        ("https://v3.douyinvod.com/video.mp4", "https://www.douyin.com/"),
        ("https://v5-dy-o.zjcdn.com/video.mp4", "https://www.douyin.com/"),
        ("https://www.douyin.com/aweme/v1/play/", "https://www.douyin.com/"),
        ("https://tymov2.a.kwimgs.com/video.mp4", "https://v.kuaishou.com/"),
        ("https://sns-v11.rednotecdn.com/video.mp4", "https://sns-v11.rednotecdn.com/"),
        ("https://example.com/video.mp4", "https://example.com/"),
        ("https://another.akamaized.net/video.mp4", "https://another.akamaized.net/"),
        (
            "https://bilivideo.com.example.org/video.mp4",
            "https://bilivideo.com.example.org/",
        ),
    ],
)
def test_other_platform_referers_are_unchanged(url, referer):
    assert _download_request_headers(url)["Referer"] == referer


@pytest.mark.parametrize("range_request", [False, True])
def test_bilibili_proxy_streams_with_platform_referer(
    monkeypatch, tmp_path, range_request
):
    monkeypatch.setattr(web, "DOWNLOAD_PROXY_MODE_FILE", tmp_path / "mode.json")
    monkeypatch.setattr(web, "PUBLIC_BASE_URL", "https://download.example.com")
    target = "https://upos-hz-mirrorakam.akamaized.net/video.mp4"
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == target
        assert request.headers["Referer"] == "https://www.bilibili.com/"
        if range_request:
            assert request.headers["Range"] == "bytes=0-"
        else:
            assert "Range" not in request.headers
        headers = {"Content-Type": "video/mp4", "Content-Length": "4"}
        if range_request:
            headers["Content-Range"] = "bytes 0-3/4"
        return httpx.Response(
            206 if range_request else 200, headers=headers, content=b"test"
        )

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        web.httpx,
        "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    signed = web._build_download_proxy_url(target, None)
    headers = {"Range": "bytes=0-3"} if range_request else {}
    response = TestClient(web.app).get(
        "/api/download", params=parse_qs(urlparse(signed).query), headers=headers
    )
    assert len(requests) == 1
    assert response.status_code == (206 if range_request else 200)
    assert response.content == b"test"
    assert response.headers["content-type"].startswith("video/mp4")
    assert 'filename="download.mp4"' in response.headers["content-disposition"]
