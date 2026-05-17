from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple


def resolve_bbox(box: Sequence[float | int], image_shape: Tuple[int, int, int] | Tuple[int, int]) -> Tuple[int, int, int, int]:
    """Resolve bbox from absolute px or relative [0..1] coordinates."""
    h, w = image_shape[:2]
    if len(box) != 4:
        raise ValueError(f"BBox must have 4 values, got: {box}")

    values = [float(v) for v in box]
    if max(values) <= 1.0001:
        x1 = int(round(values[0] * w))
        y1 = int(round(values[1] * h))
        x2 = int(round(values[2] * w))
        y2 = int(round(values[3] * h))
    else:
        x1, y1, x2, y2 = [int(round(v)) for v in values]

    x1 = max(0, min(w - 1, x1))
    y1 = max(0, min(h - 1, y1))
    x2 = max(x1 + 1, min(w, x2))
    y2 = max(y1 + 1, min(h, y2))
    return x1, y1, x2, y2


def resolve_bboxes(boxes: Iterable[Sequence[float | int]], image_shape: Tuple[int, int, int] | Tuple[int, int]) -> List[Tuple[int, int, int, int]]:
    return [resolve_bbox(box, image_shape) for box in boxes]
