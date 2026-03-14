"""
Data cleaning pipeline.

Steps:
1. Deduplication by hash(content) + platform
2. Filter: remove non-Chinese, too short/long texts
3. Clean emojis, control characters, HTML tags, extra whitespace
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from typing import Any

try:
    import emoji
    _HAS_EMOJI = True
except ImportError:
    _HAS_EMOJI = False

logger = logging.getLogger(__name__)

# Minimum/maximum character length for useful content
_MIN_LEN = 5
_MAX_LEN = 1000

# Chinese character range (CJK Unified Ideographs)
_CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EXTRA_SPACE_PATTERN = re.compile(r"[ \t]+")
_BLANK_LINE_PATTERN = re.compile(r"\n{3,}")


def _clean_text(text: str) -> str:
    """Clean a single text string."""
    # Remove HTML tags
    text = _HTML_TAG_PATTERN.sub("", text)
    # Replace HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    # Remove control characters (keep newlines and tabs)
    text = _CONTROL_CHAR_PATTERN.sub("", text)
    # Remove emoji if library available, else keep
    if _HAS_EMOJI:
        text = emoji.replace_emoji(text, replace="")
    # Normalize unicode
    text = unicodedata.normalize("NFKC", text)
    # Collapse extra spaces
    text = _EXTRA_SPACE_PATTERN.sub(" ", text)
    # Collapse multiple blank lines
    text = _BLANK_LINE_PATTERN.sub("\n\n", text)
    return text.strip()


def _has_sufficient_chinese(text: str) -> bool:
    """Return True if text contains at least a few Chinese characters."""
    chinese_chars = _CHINESE_PATTERN.findall(text)
    return len(chinese_chars) >= 2


def _is_valid_length(text: str) -> bool:
    return _MIN_LEN <= len(text) <= _MAX_LEN


def _content_hash(platform: str, content: str) -> str:
    key = f"{platform}::{content}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def clean(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clean and deduplicate a list of raw crawler records.

    Returns a list of cleaned records, retaining all original fields.
    The ``content`` field is replaced with the cleaned text.
    """
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    total = len(records)
    skipped_dup = 0
    skipped_lang = 0
    skipped_len = 0

    for record in records:
        platform = record.get("platform", "")
        raw_content = record.get("content", "")

        if not isinstance(raw_content, str):
            raw_content = str(raw_content)

        text = _clean_text(raw_content)

        # Length filter
        if not _is_valid_length(text):
            skipped_len += 1
            continue

        # Language filter
        if not _has_sufficient_chinese(text):
            skipped_lang += 1
            continue

        # Deduplication
        h = _content_hash(platform, text)
        if h in seen:
            skipped_dup += 1
            continue
        seen.add(h)

        cleaned_record = {**record, "content": text}
        cleaned.append(cleaned_record)

    logger.info(
        "Cleaning: total=%d  kept=%d  dup=%d  lang=%d  len=%d",
        total,
        len(cleaned),
        skipped_dup,
        skipped_lang,
        skipped_len,
    )
    return cleaned
