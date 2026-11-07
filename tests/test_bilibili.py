import httpx
import pytest

from parse_video_py.parser.bilibili import BiliBili


def _mock_client(monkeypatch, handler):
    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "parse_video_py.parser.bilibili.httpx.AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.asyncio
async def test_video_uses_distinct_view_and_play_headers(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["Referer"] == "https://www.bilibili.com/"
        assert request.url.params["bvid"] == "BV1AL411Z7xb"
        if request.url.path == "/x/web-interface/view":
            assert request.headers["User-Agent"] == "okhttp/4.9.3"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "title": "Test video",
                        "pic": "https://example.com/cover.jpg",
                        "pages": [{"cid": 1029052191}],
                        "owner": {"mid": 1, "name": "Author", "face": ""},
                    },
                },
            )
        assert request.url.path == "/x/player/playurl"
        assert request.headers["User-Agent"] == BiliBili.USER_AGENT
        assert request.url.params["cid"] == "1029052191"
        assert request.url.params["platform"] == "html5"
        assert request.url.params["fnval"] == "0"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"durl": [{"url": "https://example.com/video.mp4"}]},
            },
        )

    _mock_client(monkeypatch, handler)
    parser = BiliBili()
    info = await parser.parse_share_url(
        "https://www.bilibili.com/video/BV1AL411Z7xb/?spm_id_from=333.788.videopod.sections"
    )
    assert len(requests) == 2
    assert info.video_url == "https://example.com/video.mp4"
    assert info.title == "Test video"
    assert info.author.name == "Author"
    assert parser.get_default_headers()["User-Agent"] == BiliBili.USER_AGENT


@pytest.mark.asyncio
@pytest.mark.parametrize("api_path", ["/x/web-interface/view", "/x/player/playurl"])
async def test_412_has_specific_bilibili_error_without_retry(monkeypatch, api_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(412)

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match=r"B站暂时限制了服务器访问.*HTTP 412"):
        await BiliBili()._send_bili_request("https://api.bilibili.com" + api_path)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_short_link_keeps_browser_headers(monkeypatch):
    def handler(request):
        assert request.headers["User-Agent"] == BiliBili.USER_AGENT
        return httpx.Response(
            302, headers={"Location": "https://www.bilibili.com/video/BV1AL411Z7xb/"}
        )

    _mock_client(monkeypatch, handler)
    assert await BiliBili()._get_bvid_from_url("https://b23.tv/test") == "BV1AL411Z7xb"
