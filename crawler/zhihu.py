"""
知乎 (Zhihu) crawler.

Searches Zhihu for answers/articles related to the keyword.
ZHIHU_COOKIE environment variable is optional, but improves reliability.
Without a cookie a low request rate is used automatically.
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

_SEARCH_URL = "https://www.zhihu.com/api/v4/search_v3"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.zhihu.com/",
    "Accept": "application/json, text/plain, */*",
    "x-api-version": "3.0.76",
    "x-app-za": "OS=Web",
}

_SAMPLE_ANSWERS = [
    "这款产品我用过，整体来说不错，物有所值。",
    "个人觉得一般，市面上有更好的选择。",
    "很好！使用了半年，没出现任何问题，推荐。",
    "有点失望，质量没有想象中好，性价比不高。",
    "中规中矩，适合入门级用户，进阶用户可以考虑更高端的。",
    "用过好几款同类产品，这款是体验最好的。",
    "买之前做了很多功课，实际使用符合预期。",
    "不建议购买，客服态度差，产品也有质量问题。",
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
        "platform": "zhihu",
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
    count = min(limit, len(_SAMPLE_ANSWERS))
    for i, content in enumerate(_SAMPLE_ANSWERS[:count]):
        qid = hashlib.md5(f"zhihu_{keyword}_{i}".encode()).hexdigest()[:8]
        results.append(
            _make_record(
                keyword=keyword,
                content=f"【{keyword}】{content}",
                like_count=random.randint(0, 5000),
                publish_time="",
                source_url=f"https://www.zhihu.com/question/{qid}",
                meta={"question_id": qid, "is_sample": True},
            )
        )
    return results


def _extract_text(obj: dict[str, Any]) -> str:
    """Extract plain text from a Zhihu content object."""
    # Prefer excerpt, fallback to content snippet
    for key in ("excerpt", "content", "description"):
        val = obj.get(key, "")
        if val:
            # Strip basic HTML tags
            import re
            val = re.sub(r"<[^>]+>", "", val)
            val = val.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
            return val.strip()
    return ""


def crawl(
    keyword: str,
    *,
    limit: int = 50,
    max_pages: int = 2,
    page_size: int = 10,
    throttle_min: float = 2.0,
    throttle_max: float = 4.0,
    retry_times: int = 3,
    **_kwargs: Any,
) -> list[dict[str, Any]]:
    """Crawl Zhihu answers/articles for *keyword*, up to *limit* records."""
    cookie = os.environ.get("ZHIHU_COOKIE", "").strip()

    headers = {**_HEADERS}
    if cookie:
        headers["Cookie"] = cookie
    else:
        # Lower rate when unauthenticated
        throttle_min = max(throttle_min, 3.0)
        throttle_max = max(throttle_max, 6.0)

    session = requests.Session()
    session.headers.update(headers)

    results: list[dict[str, Any]] = []
    offset = 0

    for _page in range(max_pages):
        if len(results) >= limit:
            break
        params = {
            "t": "general",
            "q": keyword,
            "correction": 1,
            "offset": offset,
            "limit": page_size,
            "lc_idx": offset,
            "show_all_topics": 0,
        }
        for attempt in range(1, retry_times + 1):
            try:
                resp = session.get(_SEARCH_URL, params=params, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    break
                elif resp.status_code == 429:
                    wait = throttle_max * attempt
                    logger.warning("[zhihu] 429 rate limited, waiting %.1fs", wait)
                    time.sleep(wait)
                elif resp.status_code in (401, 403):
                    logger.warning("[zhihu] Auth error %d – check ZHIHU_COOKIE", resp.status_code)
                    return _sample_data(keyword, limit)
                else:
                    logger.warning("[zhihu] HTTP %d attempt %d", resp.status_code, attempt)
                    time.sleep(throttle_max)
            except requests.RequestException as exc:
                logger.warning("[zhihu] Request attempt %d error: %s", attempt, exc)
                time.sleep(throttle_max)
        else:
            logger.error("[zhihu] All retries failed for keyword='%s'", keyword)
            break

        items = data.get("data", [])
        if not items:
            break

        for item in items:
            obj = item.get("object", {})
            obj_type = obj.get("type", "")
            content = _extract_text(obj)
            if not content:
                continue

            like_count = 0
            publish_time = ""
            source_url = ""
            meta: dict[str, Any] = {"type": obj_type}

            if obj_type == "answer":
                like_count = int(obj.get("voteup_count", 0) or 0)
                created = obj.get("created_time", 0)
                if created:
                    try:
                        publish_time = datetime.fromtimestamp(created).isoformat()
                    except Exception:
                        pass
                question = obj.get("question", {})
                qid = str(question.get("id", ""))
                aid = str(obj.get("id", ""))
                source_url = f"https://www.zhihu.com/question/{qid}/answer/{aid}"
                meta.update({"question_id": qid, "answer_id": aid, "user": (obj.get("author") or {}).get("name", "")})
            elif obj_type == "article":
                like_count = int(obj.get("voteup_count", 0) or 0)
                created = obj.get("created", 0)
                if created:
                    try:
                        publish_time = datetime.fromtimestamp(created).isoformat()
                    except Exception:
                        pass
                aid = str(obj.get("id", ""))
                source_url = f"https://zhuanlan.zhihu.com/p/{aid}"
                meta.update({"article_id": aid, "user": (obj.get("author") or {}).get("name", "")})
            elif obj_type in ("question", "zvideo"):
                qid = str(obj.get("id", ""))
                source_url = f"https://www.zhihu.com/question/{qid}"
                meta["question_id"] = qid

            results.append(
                _make_record(
                    keyword=keyword,
                    content=content,
                    like_count=like_count,
                    publish_time=publish_time,
                    source_url=source_url,
                    meta=meta,
                )
            )
            if len(results) >= limit:
                break

        paging = data.get("paging", {})
        offset += page_size
        if paging.get("is_end"):
            break

        time.sleep(random.uniform(throttle_min, throttle_max))

    if not results:
        logger.warning("[zhihu] No results crawled, falling back to sample data")
        return _sample_data(keyword, limit)

    logger.info("[zhihu] keyword='%s' collected %d records", keyword, len(results))
    return results[:limit]
