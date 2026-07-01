import base64
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from parse_video_py import web
from parse_video_py.parser import douyin
from parse_video_py.parser.base import ImgInfo, VideoAuthor, VideoInfo, VideoQuality

client = TestClient(web.app)
AUTH_HEADERS = {"x-auth-token": "wxd8f9c2a1b3_my_secret_pwd"}
MINIPROGRAM_HEADERS = {"x-api-key": "HinsCheung_Love_Video_Parser_2026_No_Copy"}


def _basic_admin_headers(
    username: str = "hinspath@gmail.com",
    password: str = "WhatFuck.1",
) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_admin_page_requires_basic_auth():
    response = client.get("/admin")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


def test_admin_page_accepts_basic_auth():
    response = client.get("/admin", headers=_basic_admin_headers())

    assert response.status_code == 200
    assert "Admin" in response.text


def test_share_url_parse_web_entry_is_public_when_turnstile_disabled():
    response = client.get("/video/share/url/parse", params={"url": "这不是链接"})

    assert response.status_code == 200
    assert response.json()["code"] == 400


def test_share_url_parse_returns_400_when_no_url_found():
    response = client.get(
        "/video/share/url/parse",
        params={"url": "这不是链接"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {"code": 400, "msg": "未检测到有效的分享链接"}


def test_share_url_parse_returns_400_for_empty_string():
    response = client.get(
        "/video/share/url/parse",
        params={"url": ""},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {"code": 400, "msg": "未检测到有效的分享链接"}


def test_share_url_parse_returns_400_for_partial_url_without_scheme():
    response = client.get(
        "/video/share/url/parse",
        params={"url": "example.com/video/123"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {"code": 400, "msg": "未检测到有效的分享链接"}


def test_share_url_parse_returns_422_when_url_param_missing():
    response = client.get("/video/share/url/parse", headers=AUTH_HEADERS)

    assert response.status_code == 422


def test_update_cookie_api_rejects_wrong_password():
    response = client.post(
        "/api/update_cookie",
        json={"password": "wrong", "cookie": "ttwid=abc"},
    )

    assert response.status_code == 403
    assert response.json() == {"code": 403, "msg": "管理密码错误"}


def test_update_cookie_api_updates_global_cookie(monkeypatch, tmp_path):
    cookie_file = tmp_path / "douyin_cookie.txt"
    monkeypatch.setattr(web, "DOUYIN_COOKIE_FILE", cookie_file)
    original_cookie = douyin.GLOBAL_DY_COOKIE
    try:
        response = client.post(
            "/api/update_cookie",
            json={"password": "WhatFuck.1", "cookie": "  ttwid=abc  "},
        )

        assert response.status_code == 200
        assert response.json() == {
            "code": 200,
            "msg": "Cookie 更新成功，已保存，重启后仍生效",
        }
        assert cookie_file.read_text(encoding="utf-8") == "ttwid=abc"
        assert douyin.GLOBAL_DY_COOKIE == "ttwid=abc"
    finally:
        douyin.GLOBAL_DY_COOKIE = original_cookie


def test_legacy_parse_accepts_miniprogram_api_key(monkeypatch, tmp_path):
    monkeypatch.setattr(
        web,
        "DOWNLOAD_PROXY_MODE_FILE",
        tmp_path / "download_proxy_mode.json",
    )

    async def fake_parse_video_share_url(url):
        assert url == "https://v.douyin.com/test/"
        return VideoInfo(
            video_url="https://video.example/a.mp4",
            cover_url="https://image.example/cover.jpg",
            title="demo",
            video_urls=[
                VideoQuality(
                    label="1080P",
                    url="https://video.example/a-1080.mp4",
                    gear_name="normal_1080_0",
                    bit_rate=668308,
                )
            ],
            images=[
                ImgInfo(
                    url="https://image.example/1.jpg",
                    live_photo_url="https://video.example/live.mp4",
                )
            ],
            author=VideoAuthor(name="author", avatar="https://image.example/a.jpg"),
        )

    monkeypatch.setattr(web, "parse_video_share_url", fake_parse_video_share_url)

    response = client.get(
        "/api/parse",
        params={"url": "https://v.douyin.com/test/"},
        headers=MINIPROGRAM_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 200
    assert payload["data"]["video_url"] == "https://video.example/a.mp4"
    assert payload["data"]["url"] == "https://video.example/a.mp4"
    assert payload["data"]["cover"] == "https://image.example/cover.jpg"
    assert payload["data"]["download_proxy_enabled"] is True
    assert payload["data"]["download_url"].startswith("http://testserver/api/download?")
    assert payload["data"]["cover_download_url"].startswith(
        "http://testserver/api/download?"
    )
    assert payload["data"]["qualities"][0]["label"] == "1080P"
    assert payload["data"]["qualities"][0]["url"] == "https://video.example/a-1080.mp4"
    assert payload["data"]["qualities"][0]["download_url"].startswith(
        "http://testserver/api/download?"
    )
    assert payload["data"]["images"][0]["local_url"] == "https://image.example/1.jpg"
    assert (
        payload["data"]["images"][0]["local_live_photo_url"]
        == "https://video.example/live.mp4"
    )
    assert payload["data"]["images"][0]["download_url"].startswith(
        "http://testserver/api/download?"
    )
    assert payload["data"]["images"][0]["live_photo_download_url"].startswith(
        "http://testserver/api/download?"
    )

    parsed_download = urlparse(payload["data"]["download_url"])
    params = parse_qs(parsed_download.query)
    assert (
        web._verify_download_proxy_params(
            params["u"][0],
            int(params["e"][0]),
            params["s"][0],
        )
        == "https://video.example/a.mp4"
    )


def test_legacy_analysis_alias_accepts_miniprogram_api_key(monkeypatch):
    async def fake_parse_video_share_url(url):
        return VideoInfo(
            video_url="https://video.example/a.mp4",
            cover_url="",
            title="demo",
        )

    monkeypatch.setattr(web, "parse_video_share_url", fake_parse_video_share_url)

    response = client.get(
        "/api/analysis",
        params={"url": "https://v.douyin.com/test/"},
        headers=MINIPROGRAM_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["data"]["url"] == "https://video.example/a.mp4"


def test_legacy_resolve_redirect_uses_miniprogram_api_key(monkeypatch):
    async def fake_resolve_redirect_url(url):
        assert url == "https://video.example/a.mp4?x=1"
        return "https://cdn.example/a.mp4?x=1"

    monkeypatch.setattr(web, "_resolve_redirect_url", fake_resolve_redirect_url)

    response = client.get(
        "/api/resolve_redirect",
        params={"url": "https://video.example/a.mp4?x=1"},
        headers=MINIPROGRAM_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {"code": 200, "url": "https://cdn.example/a.mp4?x=1"}


def test_download_proxy_rejects_bad_signature(monkeypatch, tmp_path):
    monkeypatch.setattr(
        web,
        "DOWNLOAD_PROXY_MODE_FILE",
        tmp_path / "download_proxy_mode.json",
    )
    encoded_url = web._encode_download_url("https://video.example/a.mp4")

    response = client.get(
        "/api/download",
        params={"u": encoded_url, "e": 4102444800, "s": "bad-signature"},
    )

    assert response.status_code == 403
    assert response.json()["msg"] == "invalid download signature"


def test_download_proxy_mode_can_disable_proxy_fields(monkeypatch, tmp_path):
    mode_file = tmp_path / "download_proxy_mode.json"
    monkeypatch.setattr(web, "DOWNLOAD_PROXY_MODE_FILE", mode_file)

    async def fake_parse_video_share_url(url):
        return VideoInfo(
            video_url="https://video.example/a.mp4",
            cover_url="https://image.example/cover.jpg",
            title="demo",
            images=[ImgInfo(url="https://image.example/1.jpg")],
        )

    monkeypatch.setattr(web, "parse_video_share_url", fake_parse_video_share_url)

    update_response = client.post(
        "/api/download_proxy_mode",
        json={"enabled": False},
        headers=AUTH_HEADERS,
    )
    parse_response = client.get(
        "/api/parse",
        params={"url": "https://v.douyin.com/test/"},
        headers=MINIPROGRAM_HEADERS,
    )

    assert update_response.status_code == 200
    payload = parse_response.json()["data"]
    assert payload["download_proxy_enabled"] is False
    assert "download_url" not in payload
    assert "cover_download_url" not in payload
    assert "download_url" not in payload["images"][0]


def test_download_proxy_endpoint_rejects_when_mode_disabled(monkeypatch, tmp_path):
    mode_file = tmp_path / "download_proxy_mode.json"
    monkeypatch.setattr(web, "DOWNLOAD_PROXY_MODE_FILE", mode_file)
    web._write_download_proxy_enabled(False)
    encoded_url = web._encode_download_url("https://video.example/a.mp4")
    expires = 4102444800
    signature = web._sign_download_url(encoded_url, expires)

    response = client.get(
        "/api/download",
        params={"u": encoded_url, "e": expires, "s": signature},
    )

    assert response.status_code == 403
    assert response.json()["msg"] == "download proxy disabled"


def test_legacy_error_report_endpoints_use_miniprogram_api_key(monkeypatch, tmp_path):
    monkeypatch.setattr(web, "ERROR_REPORT_FILE", tmp_path / "error_domains.json")

    empty_response = client.get("/api/get_errors", headers=MINIPROGRAM_HEADERS)
    assert empty_response.status_code == 200
    assert empty_response.json() == []

    report_response = client.post(
        "/api/report_error",
        json={"domain": "https://v3-dy-o.zjcdn.com/path?a=1"},
        headers=MINIPROGRAM_HEADERS,
    )
    duplicate_response = client.post(
        "/api/report_error",
        json={"domain": "v3-dy-o.zjcdn.com"},
        headers=MINIPROGRAM_HEADERS,
    )
    list_response = client.get("/api/get_errors", headers=MINIPROGRAM_HEADERS)

    assert report_response.status_code == 200
    assert duplicate_response.status_code == 200
    assert list_response.json() == ["v3-dy-o.zjcdn.com"]


def test_legacy_get_errors_is_public(monkeypatch, tmp_path):
    error_file = tmp_path / "error_domains.json"
    error_file.write_text('["https://cdn.example.com/path"]', encoding="utf-8")
    monkeypatch.setattr(web, "ERROR_REPORT_FILE", error_file)

    response = client.get("/api/get_errors")

    assert response.status_code == 200
    assert response.json() == ["cdn.example.com"]


def test_legacy_delete_error_requires_auth(monkeypatch, tmp_path):
    error_file = tmp_path / "error_domains.json"
    error_file.write_text('["cdn.example.com"]', encoding="utf-8")
    monkeypatch.setattr(web, "ERROR_REPORT_FILE", error_file)

    response = client.post("/api/delete_error", json={"domain": "cdn.example.com"})

    assert response.status_code == 403


def test_legacy_delete_error_removes_one_domain(monkeypatch, tmp_path):
    error_file = tmp_path / "error_domains.json"
    error_file.write_text(
        '["cdn.example.com", "v3-dy-o.zjcdn.com"]',
        encoding="utf-8",
    )
    monkeypatch.setattr(web, "ERROR_REPORT_FILE", error_file)

    response = client.post(
        "/api/delete_error",
        json={"domain": "https://cdn.example.com/path"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["data"] == ["v3-dy-o.zjcdn.com"]
    assert client.get("/api/get_errors").json() == ["v3-dy-o.zjcdn.com"]


def test_legacy_clear_errors_removes_all_domains(monkeypatch, tmp_path):
    error_file = tmp_path / "error_domains.json"
    error_file.write_text('["cdn.example.com"]', encoding="utf-8")
    monkeypatch.setattr(web, "ERROR_REPORT_FILE", error_file)

    response = client.post("/api/clear_errors", json={}, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert client.get("/api/get_errors").json() == []
