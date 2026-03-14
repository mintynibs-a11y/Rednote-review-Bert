#!/usr/bin/env python3
"""
End-to-end pipeline: crawl → clean → BERT sentiment → summarise.

Usage
-----
    python scripts/run_all.py \\
        --keywords-file configs/keywords.txt \\
        --platforms xhs,jd,bilibili,zhihu \\
        --limit-per-platform 50 \\
        --model-name uer/roberta-base-finetuned-jd-binary-chinese
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

_RAW_DIR = _REPO_ROOT / "data" / "raw"
_CLEAN_DIR = _REPO_ROOT / "data" / "clean"
_OUTPUT_DIR = _REPO_ROOT / "data" / "output"
_LOGS_DIR = _REPO_ROOT / "logs"

for _d in (_RAW_DIR, _CLEAN_DIR, _OUTPUT_DIR, _LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_FILE = _LOGS_DIR / "app.log"


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s – %(message)s"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)


logger = logging.getLogger("run_all")

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
_DEFAULT_MODEL = "uer/roberta-base-finetuned-jd-binary-chinese"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-platform comment crawler + BERT sentiment pipeline"
    )
    parser.add_argument(
        "--keywords-file",
        default=str(_REPO_ROOT / "configs" / "keywords.txt"),
        help="Path to keywords file (one keyword per line)",
    )
    parser.add_argument(
        "--platforms",
        default="xhs,jd,bilibili,zhihu",
        help="Comma-separated list of platforms to crawl",
    )
    parser.add_argument(
        "--limit-per-platform",
        type=int,
        default=50,
        help="Max records per platform per keyword",
    )
    parser.add_argument(
        "--model-name",
        default=_DEFAULT_MODEL,
        help="Hugging Face model for sentiment analysis",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Inference batch size",
    )
    parser.add_argument(
        "--skip-sentiment",
        action="store_true",
        help="Skip sentiment analysis (useful for crawl-only runs)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--platforms-config",
        default=str(_REPO_ROOT / "configs" / "platforms.yaml"),
        help="Path to platforms YAML config",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_keywords(path: str) -> list[str]:
    keywords: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                keywords.append(line)
    if not keywords:
        raise ValueError(f"No keywords found in {path}")
    return keywords


def _load_platform_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("platforms", {})


def _save_json(obj: object, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    logger.info("Saved %s", path)


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------

def _crawl_platform(
    platform: str,
    keyword: str,
    limit: int,
    platform_cfg: dict,
) -> list[dict]:
    try:
        mod = importlib.import_module(f"crawler.{platform}")
    except ImportError as exc:
        logger.error("Cannot import crawler for platform '%s': %s", platform, exc)
        return []

    cfg = platform_cfg.get(platform, {})
    if not cfg.get("enabled", True):
        logger.info("Platform '%s' is disabled in config, skipping.", platform)
        return []

    kwargs = {
        "limit": limit,
        "max_pages": cfg.get("max_pages", 3),
        "page_size": cfg.get("page_size", 20),
        "throttle_min": cfg.get("throttle_min", 1.0),
        "throttle_max": cfg.get("throttle_max", 2.0),
        "retry_times": cfg.get("retry_times", 3),
    }

    logger.info("Crawling platform='%s' keyword='%s' limit=%d …", platform, keyword, limit)
    try:
        records = mod.crawl(keyword, **kwargs)
        logger.info(
            "Platform='%s' keyword='%s': got %d records", platform, keyword, len(records)
        )
        return records
    except Exception as exc:
        logger.error(
            "Platform='%s' keyword='%s' crawl error: %s", platform, keyword, exc, exc_info=True
        )
        return []


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _build_summary(df: pd.DataFrame) -> dict:
    summary: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_records": len(df),
        "by_platform": {},
        "by_keyword": {},
        "by_platform_keyword": {},
    }

    for platform, grp in df.groupby("platform"):
        counts = grp["sentiment_label"].value_counts().to_dict() if "sentiment_label" in grp else {}
        total = len(grp)
        summary["by_platform"][platform] = {
            "total": total,
            "sentiment_counts": counts,
            "sentiment_ratios": {k: round(v / total, 3) for k, v in counts.items()} if total else {},
        }

    for keyword, grp in df.groupby("keyword"):
        counts = grp["sentiment_label"].value_counts().to_dict() if "sentiment_label" in grp else {}
        total = len(grp)
        summary["by_keyword"][keyword] = {
            "total": total,
            "sentiment_counts": counts,
            "sentiment_ratios": {k: round(v / total, 3) for k, v in counts.items()} if total else {},
        }

    if "sentiment_label" in df.columns:
        for (platform, keyword), grp in df.groupby(["platform", "keyword"]):
            key = f"{platform}::{keyword}"
            counts = grp["sentiment_label"].value_counts().to_dict()
            total = len(grp)
            summary["by_platform_keyword"][key] = {
                "total": total,
                "sentiment_counts": counts,
                "sentiment_ratios": {k: round(v / total, 3) for k, v in counts.items()} if total else {},
            }

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = _parse_args()
    _setup_logging(args.verbose)

    logger.info("=" * 60)
    logger.info("Multi-platform crawler + BERT sentiment pipeline")
    logger.info("=" * 60)

    # Load keywords
    keywords = _load_keywords(args.keywords_file)
    logger.info("Keywords (%d): %s", len(keywords), keywords)

    # Load platform config
    platform_cfg = _load_platform_config(args.platforms_config)

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    logger.info("Platforms: %s", platforms)

    # ---- Crawl ----------------------------------------------------------------
    all_raw: list[dict] = []
    crawl_failures = 0

    for platform in platforms:
        for keyword in keywords:
            records = _crawl_platform(platform, keyword, args.limit_per_platform, platform_cfg)
            if not records:
                crawl_failures += 1
            all_raw.extend(records)

    logger.info("Crawl complete: %d raw records, %d failures", len(all_raw), crawl_failures)

    if not all_raw:
        logger.error("No records collected. Exiting.")
        return 1

    # Save raw data
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    raw_path = _RAW_DIR / f"raw_{run_ts}.json"
    _save_json(all_raw, raw_path)

    # ---- Clean ----------------------------------------------------------------
    from pipeline.cleaning import clean

    cleaned = clean(all_raw)
    logger.info("After cleaning: %d records", len(cleaned))

    if not cleaned:
        logger.error("All records were filtered out. Check your keywords or platform config.")
        return 1

    clean_path = _CLEAN_DIR / f"clean_{run_ts}.json"
    _save_json(cleaned, clean_path)

    # ---- Sentiment ------------------------------------------------------------
    if args.skip_sentiment:
        logger.info("Skipping sentiment analysis (--skip-sentiment flag set)")
        results = cleaned
        for r in results:
            r.setdefault("sentiment_label", "")
            r.setdefault("sentiment_score", None)
    else:
        from pipeline.sentiment import run_sentiment

        results = run_sentiment(
            cleaned,
            model_name=args.model_name,
            batch_size=args.batch_size,
        )

    # ---- Save results ---------------------------------------------------------
    df = pd.DataFrame(results)

    # Flatten meta dict for CSV output
    if "meta" in df.columns:
        df["meta"] = df["meta"].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else x)

    sentiment_csv = _OUTPUT_DIR / "sentiment_results.csv"
    df.to_csv(sentiment_csv, index=False, encoding="utf-8-sig")
    logger.info("Results saved to %s (%d rows)", sentiment_csv, len(df))

    # ---- Summary --------------------------------------------------------------
    summary = _build_summary(df)
    summary_json = _OUTPUT_DIR / "summary.json"
    _save_json(summary, summary_json)

    # Also save a flat CSV summary
    summary_rows = []
    for key, val in summary.get("by_platform_keyword", {}).items():
        platform, keyword = key.split("::", 1)
        row = {"platform": platform, "keyword": keyword, "total": val["total"]}
        row.update({f"sentiment_{k}": v for k, v in val.get("sentiment_counts", {}).items()})
        row.update({f"ratio_{k}": v for k, v in val.get("sentiment_ratios", {}).items()})
        summary_rows.append(row)

    if summary_rows:
        summary_csv = _OUTPUT_DIR / "summary.csv"
        pd.DataFrame(summary_rows).to_csv(summary_csv, index=False, encoding="utf-8-sig")
        logger.info("Summary saved to %s", summary_csv)

    # Print final statistics
    logger.info("=" * 60)
    logger.info("Pipeline complete.")
    logger.info("  Total records: %d", summary["total_records"])
    for platform, info in summary["by_platform"].items():
        logger.info("  [%s] %d records  %s", platform, info["total"], info.get("sentiment_counts", {}))
    logger.info("  Results: %s", sentiment_csv)
    logger.info("  Summary: %s", summary_json)
    logger.info("  Log:     %s", _LOG_FILE)
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
