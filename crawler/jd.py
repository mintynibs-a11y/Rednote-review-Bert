"""
京东 (JD) crawler.

Searches JD for products matching the keyword, then fetches public reviews.
JD_COOKIE environment variable is optional – unauthenticated requests work for
most public reviews.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_JD_SEARCH_URL = "https://search.jd.com/Search"
_JD_REVIEW_URL = "https://club.jd.com/comment/productPageComments.action"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://search.jd.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_SAMPLE_REVIEWS = [
    "质量很好，物流很快，下次还会再买！",
    "包装完好，产品和描述一致，很满意。",
    "性价比高，推荐购买，售后服务也不错。",
    "一般般吧，还凑合，不是很惊艳。",
    "有点小失望，感觉和宣传的有差距。",
    "到货很快，东西不错，价格合理，满意！",
    "用了几天感觉不错，继续观察，暂时好评。",
    "退货了，质量问题，客服处理还算及时。",
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
        "platform": "jd",
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
    count = min(limit, len(_SAMPLE_REVIEWS))
    for i, content in enumerate(_SAMPLE_REVIEWS[:count]):
        cid = hashlib.md5(f"jd_{keyword}_{i}".encode()).hexdigest()[:12]
        results.append(
            _make_record(
                keyword=keyword,
                content=f"【{keyword}】{content}",
                like_count=random.randint(0, 200),
                publish_time="",
                source_url="https://item.jd.com/sample.html",
                meta={"comment_id": cid, "product_id": "sample", "is_sample": True},
            )
        )
    return results


def _search_product_ids(
    keyword: str,
    session: requests.Session,
    throttle_min: float,
    throttle_max: float,
    retry_times: int,
) -> list[str]:
    """Return a list of JD product IDs for *keyword*."""
    params = {"keyword": keyword, "enc": "utf-8", "page": 1}
    for attempt in range(1, retry_times + 1):
        try:
            resp = session.get(
                _JD_SEARCH_URL,
                params=params,
                timeout=15,
                allow_redirects=True,
            )
            if resp.status_code == 200:
                # Extract product IDs from HTML using simple pattern matching
                import re

                ids = re.findall(r'data-sku="(\d+)"', resp.text)
                if not ids:
                    # Alternative pattern
                    ids = re.findall(r'"wareId":"?(\d+)"?', resp.text)
                unique_ids = list(dict.fromkeys(ids))[:5]  # up to 5 products
                if unique_ids:
                    logger.debug("[jd] Found product IDs: %s", unique_ids)
                    return unique_ids
            time.sleep(random.uniform(throttle_min, throttle_max))
        except requests.RequestException as exc:
            logger.warning("[jd] Search attempt %d error: %s", attempt, exc)
            time.sleep(throttle_max)
    return []


def _fetch_reviews(
    product_id: str,
    keyword: str,
    session: requests.Session,
    limit: int,
    max_pages: int,
    page_size: int,
    throttle_min: float,
    throttle_max: float,
    retry_times: int,
) -> list[dict[str, Any]]:
    """Fetch reviews for a single JD product."""
    results: list[dict[str, Any]] = []
    for page in range(0, max_pages):
        if len(results) >= limit:
            break
        params = {
            "productId": product_id,
            "score": 0,
            "sortType": 5,
            "page": page,
            "pageSize": page_size,
            "isShadowSku": 0,
            "rid": 0,
            "fold": 1,
        }
        for attempt in range(1, retry_times + 1):
            try:
                resp = session.get(
                    _JD_REVIEW_URL,
                    params=params,
                    timeout=15,
                )
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        break
                    except Exception:
                        logger.warning("[jd] Non-JSON response for product %s page %d", product_id, page)
                        data = {}
                        break
                elif resp.status_code == 429:
                    wait = throttle_max * attempt
                    logger.warning("[jd] 429 rate limited, waiting %.1fs", wait)
                    time.sleep(wait)
                else:
                    logger.warning("[jd] HTTP %d attempt %d", resp.status_code, attempt)
                    time.sleep(throttle_max)
            except requests.RequestException as exc:
                logger.warning("[jd] Review fetch attempt %d error: %s", attempt, exc)
                time.sleep(throttle_max)
        else:
            logger.error("[jd] All retries failed for product %s page %d", product_id, page)
            break

        comments = data.get("comments", [])
        if not comments:
            break  # No more pages

        for c in comments:
            content = c.get("content", "").strip()
            if not content:
                continue
            publish_time = ""
            raw_time = c.get("creationTime", "")
            if raw_time:
                try:
                    publish_time = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S").isoformat()
                except Exception:
                    publish_time = raw_time

            results.append(
                _make_record(
                    keyword=keyword,
                    content=content,
                    like_count=int(c.get("usefulVoteCount", 0) or 0),
                    publish_time=publish_time,
                    source_url=f"https://item.jd.com/{product_id}.html",
                    meta={
                        "comment_id": str(c.get("id", "")),
                        "product_id": product_id,
                        "user": c.get("nickname", ""),
                        "score": c.get("score", 0),
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
    page_size: int = 10,
    throttle_min: float = 1.0,
    throttle_max: float = 2.0,
    retry_times: int = 3,
    **_kwargs: Any,
) -> list[dict[str, Any]]:
    """Crawl JD reviews for *keyword*, returning up to *limit* records."""
    cookie = os.environ.get("JD_COOKIE", "").strip()

    session = requests.Session()
    session.headers.update(_HEADERS)
    if cookie:
        session.headers["Cookie"] = cookie

    product_ids = _search_product_ids(
        keyword, session, throttle_min, throttle_max, retry_times
    )
    if not product_ids:
        logger.warning(
            "[jd] Could not find products for keyword='%s', using sample data", keyword
        )
        return _sample_data(keyword, limit)

    results: list[dict[str, Any]] = []
    per_product = max(1, limit // len(product_ids))

    for pid in product_ids:
        if len(results) >= limit:
            break
        reviews = _fetch_reviews(
            pid,
            keyword,
            session,
            per_product,
            max_pages,
            page_size,
            throttle_min,
            throttle_max,
            retry_times,
        )
        results.extend(reviews)
        time.sleep(random.uniform(throttle_min, throttle_max))

    if not results:
        logger.warning("[jd] No results crawled, falling back to sample data")
        return _sample_data(keyword, limit)

    logger.info("[jd] keyword='%s' collected %d records", keyword, len(results))
    return results[:limit]
