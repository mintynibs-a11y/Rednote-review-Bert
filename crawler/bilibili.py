"""
Bilibili (B站) crawler.

Uses the public Bilibili API.  No login is required for basic access.
Set BILI_SESSDATA environment variable to increase API quotas.

Search flow: keyword → video list → comments for each video.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
_COMMENT_URL = "https://api.bilibili.com/x/v2/reply"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}

_SAMPLE_COMMENTS = [
    "视频讲得很好，学到了很多，感谢UP主！",
    "这个产品我也买了，感觉还不错，就是价格偏贵。",
    "评测很专业，内容详尽，强烈推荐！",
    "感觉一般，比不上同价位其他品牌。",
    "用了两个月了，没啥问题，挺好用的。",
    "UP主说的对，这个产品确实值得购买。",
    "有点夸大其词了，实际体验不如视频说的好。",
    "中性评价，各有优缺点，看个人需求吧。",
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
        "platform": "bilibili",
        "keyword": keyword,
        "content": content,
        "like_count": like_count,
        "publish_time": publish_time,
        "source_url": source_url,
        "meta": meta or {},
        "crawl_time": datetime.now(timezone.utc).isoformat(),
    }


def _sample_data(keyword: str, limit: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    count = min(limit, len(_SAMPLE_COMMENTS))
    for i, content in enumerate(_SAMPLE_COMMENTS[:count]):
        vid = hashlib.md5(f"bili_{keyword}_{i}".encode()).hexdigest()[:8]
        results.append(
            _make_record(
                keyword=keyword,
                content=f"【{keyword}】{content}",
                like_count=random.randint(0, 1000),
                publish_time="",
                source_url=f"https://www.bilibili.com/video/BV{vid}",
                meta={"video_id": f"BV{vid}", "comment_id": str(i), "is_sample": True},
            )
        )
    return results


def _build_session() -> requests.Session:
    """Build a requests Session with Bilibili-appropriate headers and cookies.

    Reads two optional environment variables:
    - ``BILI_SESSDATA``: the value of the SESSDATA cookie only (most common).
    - ``BILI_COOKIE``: a full ``name=value; name=value`` cookie string
      (takes precedence over ``BILI_SESSDATA`` if both are set).
    """
    session = requests.Session()
    session.headers.update(_HEADERS)

    # Full cookie string overrides individual SESSDATA
    full_cookie = os.environ.get("BILI_COOKIE", "").strip()
    if full_cookie:
        session.headers["Cookie"] = full_cookie
        logger.debug("[bilibili] Using BILI_COOKIE for authentication")
    else:
        sessdata = os.environ.get("BILI_SESSDATA", "").strip()
        if sessdata:
            session.cookies.set("SESSDATA", sessdata, domain=".bilibili.com")
            logger.debug("[bilibili] Using BILI_SESSDATA for authentication")

    return session


def _search_videos(
    keyword: str,
    session: requests.Session,
    page: int,
    page_size: int,
    retry_times: int,
    throttle_max: float,
) -> list[dict[str, Any]]:
    """Return list of video info dicts from Bilibili search."""
    params = {
        "keyword": keyword,
        "search_type": "video",
        "page": page,
        "page_size": page_size,
        "order": "totalrank",
    }
    for attempt in range(1, retry_times + 1):
        try:
            resp = session.get(_SEARCH_URL, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data", {}).get("result", [])
                logger.warning("[bilibili] Search API error code %d: %s", data.get("code"), data.get("message"))
                return []
            logger.warning("[bilibili] HTTP %d attempt %d", resp.status_code, attempt)
            time.sleep(throttle_max)
        except requests.Timeout:
            logger.warning("[bilibili] Search timeout on attempt %d", attempt)
            time.sleep(throttle_max)
        except requests.RequestException as exc:
            logger.warning("[bilibili] Search attempt %d error: %s", attempt, exc)
            time.sleep(throttle_max)
    return []


def _fetch_comments(
    aid: int,
    bvid: str,
    keyword: str,
    session: requests.Session,
    limit: int,
    max_pages: int,
    page_size: int,
    throttle_min: float,
    throttle_max: float,
    retry_times: int,
) -> list[dict[str, Any]]:
    """Fetch top-level comments for a Bilibili video."""
    results: list[dict[str, Any]] = []
    for page_num in range(1, max_pages + 1):
        if len(results) >= limit:
            break
        params = {
            "type": 1,  # video
            "oid": aid,
            "pn": page_num,
            "ps": page_size,
            "sort": 2,  # hot sort
        }
        for attempt in range(1, retry_times + 1):
            try:
                resp = session.get(_COMMENT_URL, params=params, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        break
                    logger.warning("[bilibili] Comment API code %d", data.get("code"))
                    return results
                elif resp.status_code in (412, 429):
                    # Exponential back-off: attempt 1→1 s, 2→2 s, 3→4 s, etc.
                    backoff = 2 ** (attempt - 1)
                    logger.warning(
                        "[bilibili] HTTP %d (rate limited), back-off %.0fs (attempt %d/%d)",
                        resp.status_code, backoff, attempt, retry_times,
                    )
                    time.sleep(backoff)
                else:
                    time.sleep(throttle_max)
            except requests.Timeout:
                logger.warning(
                    "[bilibili] Comment fetch timeout on attempt %d (aid=%d)", attempt, aid
                )
                time.sleep(throttle_max)
            except requests.RequestException as exc:
                logger.warning("[bilibili] Comment attempt %d error: %s", attempt, exc)
                time.sleep(throttle_max)
        else:
            break

        replies = (data.get("data") or {}).get("replies") or []
        if not replies:
            break

        for reply in replies:
            content = (reply.get("content") or {}).get("message", "").strip()
            if not content:
                continue
            rpid = str(reply.get("rpid", ""))
            ctime = reply.get("ctime", 0)
            publish_time = ""
            if ctime:
                try:
                    publish_time = datetime.fromtimestamp(ctime).isoformat()
                except Exception:
                    pass
            member = reply.get("member") or {}
            results.append(
                _make_record(
                    keyword=keyword,
                    content=content,
                    like_count=int((reply.get("like") or 0)),
                    publish_time=publish_time,
                    source_url=f"https://www.bilibili.com/video/{bvid}",
                    meta={
                        "video_id": bvid,
                        "comment_id": rpid,
                        "user": member.get("uname", ""),
                    },
                )
            )
            if len(results) >= limit:
                break

        time.sleep(random.uniform(throttle_min, throttle_max))

    return results


def crawl(
    keyword: str,
    *,
    limit: int = 50,
    max_pages: int = 3,
    page_size: int = 20,
    throttle_min: float = 0.5,
    throttle_max: float = 1.5,
    retry_times: int = 3,
    **_kwargs: Any,
) -> list[dict[str, Any]]:
    """Crawl Bilibili video comments for *keyword*, up to *limit* records."""
    session = _build_session()
    results: list[dict[str, Any]] = []

    for search_page in range(1, max_pages + 1):
        if len(results) >= limit:
            break
        videos = _search_videos(keyword, session, search_page, page_size, retry_times, throttle_max)
        if not videos:
            logger.warning("[bilibili] No videos found for keyword='%s' page=%d", keyword, search_page)
            break

        for video in videos[:3]:  # fetch comments from top-3 videos per page
            if len(results) >= limit:
                break
            aid = video.get("aid") or video.get("id")
            bvid = video.get("bvid", f"BV{aid}")
            if not aid:
                continue

            remaining = limit - len(results)
            comments = _fetch_comments(
                int(aid),
                bvid,
                keyword,
                session,
                remaining,
                max_pages,
                page_size,
                throttle_min,
                throttle_max,
                retry_times,
            )
            results.extend(comments)
            time.sleep(random.uniform(throttle_min, throttle_max))

        time.sleep(random.uniform(throttle_min, throttle_max))

    if not results:
        logger.warning("[bilibili] No results crawled, falling back to sample data")
        return _sample_data(keyword, limit)

    logger.info("[bilibili] keyword='%s' collected %d records", keyword, len(results))
    return results[:limit]
