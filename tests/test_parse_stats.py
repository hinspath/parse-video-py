from concurrent.futures import ThreadPoolExecutor
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from parse_video_py import parse_stats, web
from parse_video_py.parser.base import ImgInfo, VideoInfo
from parse_video_py.parser.douyin import DouYinWorkUnavailable


STATS_URL = "/api/admin/parse_stats"
MINI_URL = "/api/parse"
WEB_URL = "/video/share/url/parse"
MINI_HEADERS = {"x-api-key": "test-mini-key"}


@pytest.fixture
def stats_app(monkeypatch, tmp_path):
    path = tmp_path / "runtime" / "parse_stats.sqlite3"
    monkeypatch.setattr(web, "PARSE_STATS_FILE", path)
    monkeypatch.setattr(web, "ADMIN_USERNAME", "stats-admin")
    monkeypatch.setattr(web, "ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setattr(web, "MINIPROGRAM_AUTH_MODE", "api_key")
    monkeypatch.setattr(web, "MINIPROGRAM_API_KEY", MINI_HEADERS["x-api-key"])
    monkeypatch.setattr(web, "TURNSTILE_SECRET_KEY", "")
    monkeypatch.setattr(parse_stats, "_today", lambda: date(2026, 11, 22))
    return TestClient(web.app), path


def get_stats(client, **filters):
    return client.get(
        STATS_URL,
        params=filters,
        auth=("stats-admin", "test-admin-password"),
    )


def test_stats_requires_admin_basic_auth(stats_app):
    client, path = stats_app
    for headers in ({}, MINI_HEADERS, {"x-auth-token": web.API_SECRET_TOKEN}):
        denied = client.get(STATS_URL, headers=headers)
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"].startswith("Basic")
        assert "no-store" in denied.headers["cache-control"]
    assert client.get("/admin", auth=("stats-admin", "test-admin-password")).status_code == 200
    assert client.get("/").status_code == 200

    empty = get_stats(client)
    assert empty.status_code == 200
    assert empty.headers["cache-control"] == "private, no-store"
    assert empty.json()["data"]["overall"] == {
        "total": 0, "success": 0, "failed": 0, "rate": None,
    }
    assert get_stats(client, days=999).status_code == 422
    assert get_stats(client, channel="other").status_code == 422
    assert not path.exists()


def test_parse_stats_tracks_actual_results_without_raw_data(stats_app, monkeypatch):
    client, path = stats_app

    async def parse(url):
        if "private-share-value" in url:
            raise httpx.ReadTimeout("private-observation")
        if "empty" in url:
            return VideoInfo(video_url="", cover_url="")
        return VideoInfo(
            video_url="", cover_url="",
            images=[ImgInfo(live_photo_url="https://media.example/live.mp4")],
        )

    monkeypatch.setattr(web, "parse_video_share_url", parse)
    success = client.get(MINI_URL, params={"url": "https://v.douyin.com/ok"}, headers=MINI_HEADERS)
    failure = client.get(
        "/api/analysis",
        params={"url": "https://v.douyin.com/private-share-value"},
        headers={**MINI_HEADERS, "x-douyin-cookie": "cookie-private-value"},
    )
    empty = client.get(WEB_URL, params={"url": "https://xhslink.cn/o/empty"})
    invalid = client.get(WEB_URL, params={"url": "invalid"})
    unauthorized = client.get(MINI_URL, params={"url": "https://v.douyin.com/ok"})
    assert [response.status_code for response in (success, failure, empty, invalid)] == [200] * 4
    assert [response.json()["code"] for response in (success, failure, empty, invalid)] == [200, 500, 200, 400]
    assert unauthorized.status_code == 403

    all_stats = get_stats(client, days=2).json()["data"]
    assert all_stats["start"] == "2026-11-21"
    assert all_stats["end"] == "2026-11-22"
    assert all_stats["overall"] == {"total": 4, "success": 1, "failed": 3, "rate": 25.0}
    assert all_stats["platforms"][0] == {
        "platform": "douyin", "total": 2, "success": 1, "failed": 1, "rate": 50.0,
    }
    assert {row["reason"] for row in all_stats["failures"]} == {
        "upstream_timeout", "no_media", "invalid_link",
    }
    assert get_stats(client, channel="miniprogram").json()["data"]["overall"]["rate"] == 50
    assert get_stats(client, channel="web").json()["data"]["overall"]["rate"] == 0
    for secret in (b"private-share-value", b"private-observation", b"cookie-private-value", b"test-mini-key"):
        assert secret not in path.read_bytes()


def test_stats_storage_error_does_not_break_parse(stats_app, monkeypatch):
    client, path = stats_app
    path.mkdir(parents=True)

    async def parse(_url):
        return VideoInfo(video_url="https://media.example/video.mp4", cover_url="")

    monkeypatch.setattr(web, "parse_video_share_url", parse)
    response = client.get(WEB_URL, params={"url": "https://v.douyin.com/ok"})
    assert response.json()["code"] == 200

    failed = get_stats(client)
    assert failed.status_code == 503
    assert failed.json() == {"code": 503, "msg": "解析统计暂不可用"}


def test_persistence_retention_and_windows(tmp_path, monkeypatch):
    path = tmp_path / "parse_stats.sqlite3"
    monkeypatch.setattr(parse_stats, "_today", lambda: date(2026, 10, 21))
    parse_stats.record_outcome(path, "web", "bilibili", "parser_error")
    monkeypatch.setattr(parse_stats, "_today", lambda: date(2026, 11, 20))
    parse_stats.record_outcome(path, "miniprogram", "kuaishou", "success")
    monkeypatch.setattr(parse_stats, "_today", lambda: date(2026, 11, 22))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(
            lambda _: parse_stats.record_outcome(path, "web", "douyin", "success"),
            range(12),
        ))
    assert parse_stats.read_summary(path, 2, "all")["overall"]["total"] == 12
    month = parse_stats.read_summary(path, 30, "all")
    assert month["overall"]["total"] == 13
    assert month["failures"] == []


def test_platform_classification_is_hostname_only():
    assert parse_stats.platform_for_url("https://WWW.DOUYIN.COM/video/123") == "douyin"
    assert parse_stats.platform_for_url("https://xhslink.cn/o/test") == "redbook"
    assert parse_stats.platform_for_url("https://bad.example/?q=xhslink.cn") == "unknown"
    assert parse_stats.platform_for_url("https://xhslink.cn.bad.example/") == "unknown"


def test_douyin_missing_work_has_distinct_failure_reason():
    assert parse_stats.failure_reason(DouYinWorkUnavailable()) == "upstream_no_work"
