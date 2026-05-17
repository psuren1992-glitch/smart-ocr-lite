import cv2
import numpy as np
from typing import Any, Dict, Iterator, List, Tuple


CellBox = Tuple[int, int, int, int]


def _positions(config: Dict[str, Any], axis: str) -> List[int]:
    explicit_key = f"{axis}_positions"
    if explicit_key in config:
        return [int(v) for v in config[explicit_key]]

    count_key = "cols" if axis == "x" else "rows"
    start = int(config[axis])
    step = int(config[f"{axis}_step"])
    count = int(config[count_key])
    return [start + i * step for i in range(count)]


def expand_grid(config: Dict[str, Any]) -> List[CellBox]:
    width = int(config["cell_width"])
    height = int(config["cell_height"])
    xs = _positions(config, "x")
    ys = _positions(config, "y")

    boxes: List[CellBox] = []
    for y in ys:
        for x in xs:
            boxes.append((x, y, x + width, y + height))
    return boxes


def iter_template_cells(template: Dict[str, Any]) -> Iterator[Tuple[str, int, CellBox]]:
    for name, config in template.get("cell_grids", {}).items():
        for index, bbox in enumerate(expand_grid(config)):
            yield name, index, bbox


def draw_template_cells_overlay(image: np.ndarray, template: Dict[str, Any]) -> np.ndarray:
    overlay = image.copy()
    palette = [
        (0, 120, 255),
        (0, 200, 0),
        (255, 0, 0),
        (200, 0, 200),
        (0, 180, 180),
        (180, 120, 0),
    ]

    for grid_index, (name, config) in enumerate(template.get("cell_grids", {}).items()):
        color = palette[grid_index % len(palette)]
        for index, (x1, y1, x2, y2) in enumerate(expand_grid(config)):
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 1)
            if index == 0:
                cv2.putText(
                    overlay,
                    name,
                    (x1, max(18, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    color,
                    1,
                    cv2.LINE_AA,
                )

    return overlay
