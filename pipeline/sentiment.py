"""
BERT-based sentiment analysis pipeline.

Supports any Hugging Face text-classification model.
Default model: uer/roberta-base-finetuned-jd-binary-chinese
  (binary: positive/negative; scores below a confidence threshold are labelled neutral)

For 3-class models, labels are mapped automatically.

Outputs:
  sentiment_label: positive / negative / neutral
  sentiment_score: float confidence in [0, 1]
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Default model that is known to work for Chinese product reviews
DEFAULT_MODEL = "uer/roberta-base-finetuned-jd-binary-chinese"

# Confidence threshold below which a prediction is classified as neutral
NEUTRAL_THRESHOLD = 0.70

# Normalise whatever label string the model uses → our 3 labels
_POSITIVE_RE = re.compile(r"positive|pos|好评|正面|pos_|label_1|star_[45]", re.I)
_NEGATIVE_RE = re.compile(r"negative|neg|差评|负面|neg_|label_0|star_[12]", re.I)


def _map_label(raw_label: str, score: float) -> str:
    """Map a raw model label string to positive / negative / neutral."""
    if score < NEUTRAL_THRESHOLD:
        return "neutral"
    if _POSITIVE_RE.search(raw_label):
        return "positive"
    if _NEGATIVE_RE.search(raw_label):
        return "negative"
    # For models with integer labels: label_0 is usually negative, label_1 positive
    if raw_label in ("LABEL_0", "label_0"):
        return "negative"
    if raw_label in ("LABEL_1", "label_1"):
        return "positive"
    return "neutral"


def run_sentiment(
    records: list[dict[str, Any]],
    *,
    model_name: str = DEFAULT_MODEL,
    batch_size: int = 32,
    max_length: int = 512,
    device: int = -1,  # -1 = CPU, 0+ = GPU index
) -> list[dict[str, Any]]:
    """Run sentiment inference on *records* and return augmented records.

    Each record gains two new keys:
    - ``sentiment_label``: "positive" | "negative" | "neutral"
    - ``sentiment_score``: float confidence of the top class
    """
    if not records:
        return []

    try:
        from transformers import pipeline as hf_pipeline
    except ImportError as exc:
        logger.error("transformers not installed: %s", exc)
        raise

    logger.info("Loading model '%s' (device=%d)…", model_name, device)
    try:
        classifier = hf_pipeline(
            "text-classification",
            model=model_name,
            device=device,
            truncation=True,
            max_length=max_length,
        )
    except Exception as exc:
        logger.error("Failed to load model '%s': %s", model_name, exc)
        raise

    texts = [r["content"] for r in records]
    logger.info("Running inference on %d texts (batch_size=%d)…", len(texts), batch_size)

    results_aug: list[dict[str, Any]] = []
    try:
        predictions = classifier(texts, batch_size=batch_size, truncation=True)
    except Exception as exc:
        logger.error("Inference failed: %s", exc)
        # Fallback: mark all as neutral
        predictions = [{"label": "neutral", "score": 0.0}] * len(texts)

    for record, pred in zip(records, predictions):
        raw_label = pred.get("label", "neutral")
        score = float(pred.get("score", 0.0))
        sentiment_label = _map_label(raw_label, score)
        results_aug.append(
            {
                **record,
                "sentiment_label": sentiment_label,
                "sentiment_score": round(score, 4),
            }
        )

    pos = sum(1 for r in results_aug if r["sentiment_label"] == "positive")
    neg = sum(1 for r in results_aug if r["sentiment_label"] == "negative")
    neu = sum(1 for r in results_aug if r["sentiment_label"] == "neutral")
    logger.info(
        "Sentiment done: positive=%d  negative=%d  neutral=%d", pos, neg, neu
    )
    return results_aug
