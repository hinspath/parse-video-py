import json

import httpx
import pytest

from parse_video_py.parser.redbook import RedBook

SHARE_URL = "https://xhslink.cn/o/4gG8wLbg1UP"
NOTE_URL = "https://www.xiaohongshu.com/discovery/item/note-id?xsec_token=share-token"
VIDEO_URL = "https://sns-video.example.com/video.mp4"


def _note_html(*, images=False):
    data = {
        "title": "Test note",
        "user": {"userId": "author-id", "nickname": "Author", "avatar": ""},
        "imageList": [
            {
                "urlDefault": "https://sns-img.example.com/notes_pre_post/image-id!webp",
                "livePhoto": True,
                "stream": {"h264": [{"masterUrl": VIDEO_URL}]},
            }
        ],
    }
    if not images:
        data["video"] = {"media": {"stream": {"h264": [{"masterUrl": VIDEO_URL}]}}}
    state = {
        "note": {
            "currentNoteId": "note-id",
            "noteDetailMap": {"note-id": {"note": data}},
        }
    }
    return "<script>window.__INITIAL_STATE__=" + json.dumps(state) + "</script>"


def _mock_client(monkeypatch, handler):
    async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "parse_video_py.parser.redbook.httpx.AsyncClient",
        lambda **kwargs: async_client(transport=transport, **kwargs),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("images", [False, True])
async def test_valid_video_and_live_photo_do_not_retry(monkeypatch, images):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=_note_html(images=images))

    _mock_client(monkeypatch, handler)
    info = await RedBook().parse_share_url(SHARE_URL)

    assert len(requests) == 1
    assert requests[0].headers["User-Agent"] == RedBook._USER_AGENTS[0]
    assert info.title == "Test note"
    if images:
        assert info.video_url == ""
        assert info.images[0].live_photo_url == VIDEO_URL
        assert info.images[0].url == (
            "https://ci.xiaohongshu.com/notes_pre_post/image-id?imageView2/format/jpg"
        )
    else:
        assert info.video_url == VIDEO_URL


@pytest.mark.asyncio
async def test_login_redirect_retries_share_url_with_fallback(monkeypatch):
    share_requests = []
    note_requests = []

    def handler(request):
        if str(request.url) == SHARE_URL:
            share_requests.append(request)
            assert "cookie" not in request.headers
            return httpx.Response(302, headers={"Location": NOTE_URL})
        if request.url.path == "/login":
            return httpx.Response(200, text="<html>Login</html>")
        note_requests.append(request)
        assert request.url.params["xsec_token"] == "share-token"
        if len(share_requests) == 1:
            return httpx.Response(
                302,
                headers={
                    "Location": "https://www.xiaohongshu.com/login",
                    "Set-Cookie": "blocked=1; Domain=.xiaohongshu.com; Path=/",
                },
            )
        assert "cookie" not in request.headers
        return httpx.Response(200, text=_note_html())

    _mock_client(monkeypatch, handler)
    info = await RedBook().parse_share_url(SHARE_URL)

    assert info.video_url == VIDEO_URL
    assert len(note_requests) == 2
    assert [request.headers["User-Agent"] for request in share_requests] == list(
        RedBook._USER_AGENTS
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "<html>No initial state</html>",
        '<script>window.__INITIAL_STATE__={"user": {}}</script>',
        '<script>window.__INITIAL_STATE__={"note": {}}</script>',
        '<script>window.__INITIAL_STATE__={"note": {"currentNoteId": "missing", "noteDetailMap": {}}}</script>',
        "<script>window.__INITIAL_STATE__={invalid</script>",
    ],
)
async def test_missing_note_has_friendly_error_and_bounded_retry(monkeypatch, body):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=body)

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="小红书"):
        await RedBook().parse_share_url(SHARE_URL)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_login_on_both_attempts_reports_login_requirement(monkeypatch):
    share_requests = []

    def handler(request):
        if request.url.path == "/login":
            return httpx.Response(200, text="<html>Login</html>")
        share_requests.append(request)
        return httpx.Response(
            302, headers={"Location": "https://www.xiaohongshu.com/login"}
        )

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="登录"):
        await RedBook().parse_share_url(SHARE_URL)
    assert len(share_requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429])
async def test_access_restrictions_have_friendly_error(monkeypatch, status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status)

    _mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="限制了访问"):
        await RedBook().parse_share_url(SHARE_URL)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_expired_share_link_has_friendly_error(monkeypatch):
    _mock_client(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            text='<script>window.__INITIAL_STATE__={"note": {"currentNoteId": "undefined"}}</script>',
        ),
    )
    with pytest.raises(ValueError, match="分享链接已失效"):
        await RedBook().parse_share_url(SHARE_URL)
