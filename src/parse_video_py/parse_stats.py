import asyncio
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
import httpx

from parse_video_py.parser import video_source_info_mapping


BEIJING_TIME = timezone(timedelta(hours=8))
RETENTION_DAYS = 30
_DOMAINS = {
    domain.removeprefix("www."): source.value
    for source, info in video_source_info_mapping.items()
    for domain in info["domain_list"]
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS parse_daily (
    day TEXT NOT NULL,
    channel TEXT NOT NULL,
    platform TEXT NOT NULL,
    outcome TEXT NOT NULL,
    total INTEGER NOT NULL,
    PRIMARY KEY (day, channel, platform, outcome)
)
"""


def _today() -> date:
    return datetime.now(BEIJING_TIME).date()


def platform_for_url(url: str) -> str:
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return "unknown"
    labels = host.rstrip(".").lower().split(".") if host else []
    for index in range(len(labels)):
        domain = ".".join(labels[index:])
        if domain in _DOMAINS:
            return _DOMAINS[domain]
    return "unknown"


def failure_reason(error: Exception) -> str:
    if isinstance(error, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)):
        return "upstream_timeout"
    if isinstance(error, (httpx.HTTPStatusError, aiohttp.ClientResponseError)):
        status = (
            error.response.status_code
            if isinstance(error, httpx.HTTPStatusError)
            else error.status
        )
        if status in (401, 403):
            return "upstream_denied"
        if status == 404:
            return "upstream_not_found"
        if status == 429:
            return "upstream_rate_limited"
        return "upstream_http"
    if isinstance(error, (httpx.RequestError, aiohttp.ClientError)):
        return "upstream_connection"
    if isinstance(error, ValueError) and str(error).endswith(
        "does not have source config"
    ):
        return "unsupported_platform"
    return "parser_error"


def result_outcome(data: dict) -> str:
    if any(data.get(key) for key in ("video_url", "cover_url", "music_url")):
        return "success"
    if any(
        isinstance(item, dict) and item.get("url")
        for item in data.get("video_urls") or []
    ):
        return "success"
    if any(
        isinstance(item, dict) and (item.get("url") or item.get("live_photo_url"))
        for item in data.get("images") or []
    ):
        return "success"
    return "no_media"


def record_outcome(path: Path, channel: str, platform: str, outcome: str) -> None:
    today = _today()
    oldest = today - timedelta(days=RETENTION_DAYS - 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=0.25)) as db, db:
        db.execute(_SCHEMA)
        db.execute(
            """
            INSERT INTO parse_daily VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(day, channel, platform, outcome)
            DO UPDATE SET total = total + 1
            """,
            (today.isoformat(), channel, platform, outcome),
        )
        db.execute("DELETE FROM parse_daily WHERE day < ?", (oldest.isoformat(),))


def _summary(total: int, success: int) -> dict:
    return {
        "total": total,
        "success": success,
        "failed": total - success,
        "rate": round(success * 100 / total, 1) if total else None,
    }


def read_summary(path: Path, days: int, channel: str) -> dict:
    today = _today()
    start = (today - timedelta(days=days - 1)).isoformat()
    end = today.isoformat()
    rows = []
    try:
        path.stat()
    except FileNotFoundError:
        pass
    else:
        where = "day BETWEEN ? AND ?"
        args = (start, end)
        if channel != "all":
            where += " AND channel = ?"
            args += (channel,)
        with closing(sqlite3.connect(path, timeout=0.25)) as db, db:
            db.execute(_SCHEMA)
            rows = db.execute(
                f"""
                SELECT platform, outcome, SUM(total)
                FROM parse_daily WHERE {where}
                GROUP BY platform, outcome
                """,
                args,
            ).fetchall()

    platforms = {}
    failures = {}
    for platform, outcome, count in rows:
        counts = platforms.setdefault(platform, [0, 0])
        counts[0] += count
        if outcome == "success":
            counts[1] += count
        else:
            failures[outcome] = failures.get(outcome, 0) + count

    return {
        "start": start,
        "end": end,
        "overall": _summary(
            sum(counts[0] for counts in platforms.values()),
            sum(counts[1] for counts in platforms.values()),
        ),
        "platforms": [
            {"platform": platform, **_summary(*counts)}
            for platform, counts in sorted(
                platforms.items(), key=lambda item: (-item[1][0], item[0])
            )
        ],
        "failures": [
            {"reason": reason, "count": count}
            for reason, count in sorted(
                failures.items(), key=lambda item: (-item[1], item[0])
            )
        ],
    }
