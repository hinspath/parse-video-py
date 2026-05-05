from fastapi.testclient import TestClient

from parse_video_py.parser import douyin
from parse_video_py.web import app

client = TestClient(app)
AUTH_HEADERS = {"x-auth-token": "wxd8f9c2a1b3_my_secret_pwd"}


def test_share_url_parse_requires_auth():
    response = client.get("/video/share/url/parse", params={"url": "这不是链接"})

    assert response.status_code == 403
    assert response.json() == {
        "code": 403,
        "msg": "鉴权失败：请在 Header 中提供正确的 x-auth-token",
    }


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


def test_update_cookie_api_updates_global_cookie():
    response = client.post(
        "/api/update_cookie",
        json={"password": "WhatFuck.1", "cookie": "  ttwid=abc  "},
    )

    assert response.status_code == 200
    assert response.json() == {"code": 200, "msg": "Cookie 更新成功"}
    assert douyin.GLOBAL_DY_COOKIE == "ttwid=abc"
