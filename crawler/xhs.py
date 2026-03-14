"""
小红书 (XHS) crawler.

Authentication: set XHS_COOKIE environment variable.
If cookie is absent or the request fails, the crawler returns sample data
so the overall pipeline can still run for demonstration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Minimum seconds to sleep between individual API requests (anti-rate-limit)
RATE_LIMIT_SECONDS = 2.0

_XHS_SEARCH_URL = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"
_XHS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.xiaohongshu.com/",
    "Origin": "https://www.xiaohongshu.com",
    "Content-Type": "application/json;charset=utf-8",
    "X-S": "dummy",  # Real signature required; see README
    "X-T": "0",
}

_SAMPLE_NOTES = [
    "这款产品真的超级好用，皮肤变得光滑了好多！",
    "买了一个月了，感觉效果一般，没有宣传的那么好。",
    "还可以吧，价格实惠，性价比高，但包装比较简陋。",
    "非常喜欢！已经回购第三次了，强烈推荐给大家！",
    "刚开始用有点不适应，适应之后感觉还不错。",
    "踩雷了，效果完全不对，退货处理了。",
    "中规中矩，和同价位产品差不多。",
    "种草很久了，终于入手，果然没让我失望！",
]


def _make_record(
    keyword: str,
    content: str,
    like_count: int = 0,
    publish_time: str = "",
    source_url: str = "",
    meta: dict | None = None,
) -> dict[str, Any]:
    return {
        "platform": "xhs",
        "keyword": keyword,
        "content": content,
        "like_count": like_count,
        "publish_time": publish_time,
        "source_url": source_url,
        "meta": meta or {},
        "crawl_time": datetime.now(timezone.utc).isoformat(),
    }


def _sample_data(keyword: str, limit: int) -> list[dict[str, Any]]:
    """Return deterministic sample records when real crawling is unavailable."""
    results: list[dict[str, Any]] = []
    count = min(limit, len(_SAMPLE_NOTES))
    for i, content in enumerate(_SAMPLE_NOTES[:count]):
        note_id = hashlib.md5(f"xhs_{keyword}_{i}".encode()).hexdigest()[:12]
        results.append(
            _make_record(
                keyword=keyword,
                content=f"【{keyword}】{content}",
                like_count=random.randint(0, 500),
                publish_time="",
                source_url=f"https://www.xiaohongshu.com/explore/{note_id}",
                meta={"note_id": note_id, "is_sample": True},
            )
        )
    return results


def crawl(
    keyword: str,
    *,
    limit: int = 50,
    max_pages: int = 3,
    page_size: int = 20,
    throttle_min: float = 1.5,
    throttle_max: float = 3.0,
    retry_times: int = 3,
    **_kwargs: Any,
) -> list[dict[str, Any]]:
    """Crawl XHS notes for *keyword*, returning up to *limit* records.

    Requires XHS_COOKIE environment variable with a valid web session cookie.
    Falls back to sample data if the cookie is missing or requests fail.
    """
    cookie = os.environ.get("XHS_COOKIE", "").strip()
    if not cookie:
        logger.warning(
            "[xhs] XHS_COOKIE not set – returning sample data for keyword '%s'",
            keyword,
        )
        return _sample_data(keyword, limit)

    headers = {**_XHS_HEADERS, "Cookie": cookie}
    results: list[dict[str, Any]] = []
    page = 1
    cursor = ""

    while len(results) < limit and page <= max_pages:
        payload: dict[str, Any] = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "search_id": hashlib.md5(f"{keyword}{page}".encode()).hexdigest(),
            "sort": "general",
            "note_type": 0,
        }
        if cursor:
            payload["cursor"] = cursor

        for attempt in range(1, retry_times + 1):
            try:
                resp = requests.post(
                    _XHS_SEARCH_URL,
                    headers=headers,
                    json=payload,
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") or data.get("code") == 0:
                        # Polite inter-request sleep every time we get a successful response
                        time.sleep(random.uniform(1.5, 2.5))
                        break
                    logger.warning(
                        "[xhs] keyword='%s' page=%d API error code=%s msg=%s — "
                        "Cookie 可能已失效，请重新获取 XHS_COOKIE 并刷新。",
                        keyword,
                        page,
                        data.get("code", "?"),
                        data.get("msg", "unknown"),
                    )
                    return _sample_data(keyword, limit)
                elif resp.status_code == 429:
                    wait = RATE_LIMIT_SECONDS * 2 * attempt
                    logger.warning("[xhs] 429 rate limited, waiting %.1fs", wait)
                    time.sleep(wait)
                elif resp.status_code in (401, 471):
                    logger.error(
                        "[xhs] Cookie 已过期或无效 (HTTP %d)。"
                        "请重新登录小红书并更新 XHS_COOKIE 环境变量。",
                        resp.status_code,
                    )
                    return _sample_data(keyword, limit)
                else:
                    logger.warning("[xhs] HTTP %d on attempt %d", resp.status_code, attempt)
                    time.sleep(RATE_LIMIT_SECONDS)
            except requests.RequestException as exc:
                logger.warning("[xhs] Request error attempt %d: %s", attempt, exc)
                time.sleep(RATE_LIMIT_SECONDS)
        else:
            logger.error("[xhs] All retries failed for keyword='%s' page=%d", keyword, page)
            break

        try:
            items = data.get("data", {}).get("items", [])
            cursor = data.get("data", {}).get("cursor", "")
        except Exception:
            break

        for item in items:
            note = item.get("note_card", item)
            note_id = note.get("id") or item.get("id", "")
            content_parts = [note.get("title", ""), note.get("desc", "")]
            content = " ".join(p for p in content_parts if p).strip()
            if not content:
                continue
            publish_time = ""
            ts = note.get("time") or note.get("last_update_time")
            if ts:
                try:
                    publish_time = datetime.fromtimestamp(int(ts) / 1000).isoformat()
                except Exception:
                    pass
            results.append(
                _make_record(
                    keyword=keyword,
                    content=content,
                    like_count=int(note.get("interact_info", {}).get("liked_count", 0) or 0),
                    publish_time=publish_time,
                    source_url=f"https://www.xiaohongshu.com/explore/{note_id}",
                    meta={
                        "note_id": note_id,
                        "user": note.get("user", {}).get("nickname", ""),
                    },
                )
            )
            if len(results) >= limit:
                break

        effective_min = max(throttle_min, RATE_LIMIT_SECONDS)
        effective_max = max(throttle_max, RATE_LIMIT_SECONDS)
        time.sleep(random.uniform(effective_min, effective_max))
        page += 1

    if not results:
        logger.warning("[xhs] No results crawled, falling back to sample data")
        return _sample_data(keyword, limit)

    logger.info("[xhs] keyword='%s' collected %d records", keyword, len(results))
    return results[:limit]
