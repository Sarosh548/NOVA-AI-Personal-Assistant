from __future__ import annotations

from math import isfinite, sqrt
from typing import Sequence


def cosine_similarity(
    left: Sequence[float] | None,
    right: Sequence[float] | None,
) -> float:
    """Return cosine similarity for JSON-stored embeddings without DB extensions."""
    if left is None or right is None or len(left) != len(right) or not left:
        return -1.0

    try:
        left_values = [float(value) for value in left]
        right_values = [float(value) for value in right]
    except (TypeError, ValueError):
        return -1.0

    if not all(isfinite(value) for value in left_values + right_values):
        return -1.0

    dot_product = sum(a * b for a, b in zip(left_values, right_values))
    left_norm = sqrt(sum(value * value for value in left_values))
    right_norm = sqrt(sum(value * value for value in right_values))

    if left_norm == 0.0 or right_norm == 0.0:
        return -1.0

    score = dot_product / (left_norm * right_norm)
    return max(-1.0, min(1.0, score))
