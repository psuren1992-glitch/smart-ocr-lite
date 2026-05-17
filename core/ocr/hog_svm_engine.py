import logging
from pathlib import Path
from typing import List, Optional

import cv2
import joblib
import numpy as np

from core.interfaces.ocr_engine import BaseOcrEngine
from core.models.data_models import OcrHypothesis

logger = logging.getLogger(__name__)


def _remove_border_dots(binary: np.ndarray) -> np.ndarray:
    if binary is None or binary.size == 0:
        return binary

    h, w = binary.shape[:2]
    if h < 8 or w < 8:
        return binary

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if num_labels <= 1:
        return binary

    cleaned = binary.copy()
    margin_x = max(2, int(round(w * 0.18)))
    margin_y = max(2, int(round(h * 0.18)))
    max_area = max(10, int(round((h * w) * 0.018)))
    largest_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    largest_x = int(stats[largest_label, cv2.CC_STAT_LEFT])
    largest_y = int(stats[largest_label, cv2.CC_STAT_TOP])
    largest_w = int(stats[largest_label, cv2.CC_STAT_WIDTH])
    largest_h = int(stats[largest_label, cv2.CC_STAT_HEIGHT])
    keep_box = (
        max(0, largest_x - max(2, w // 10)),
        max(0, largest_y - max(2, h // 10)),
        min(w, largest_x + largest_w + max(2, w // 10)),
        min(h, largest_y + largest_h + max(2, h // 10)),
    )

    for label in range(1, num_labels):
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        comp_w = int(stats[label, cv2.CC_STAT_WIDTH])
        comp_h = int(stats[label, cv2.CC_STAT_HEIGHT])
        area = int(stats[label, cv2.CC_STAT_AREA])
        cx, cy = centroids[label]

        near_vertical_border = x <= margin_x or (x + comp_w) >= (w - margin_x)
        near_horizontal_border = y <= margin_y or (y + comp_h) >= (h - margin_y)
        near_border = near_vertical_border or near_horizontal_border
        tiny_component = area <= max_area and comp_w <= margin_x and comp_h <= margin_y
        touches_keep_box = not (
            (x + comp_w) < keep_box[0]
            or x > keep_box[2]
            or (y + comp_h) < keep_box[1]
            or y > keep_box[3]
        )
        elongated_component = (comp_h >= max(6, int(round(h * 0.28)))) or (comp_w >= max(6, int(round(w * 0.28))))
        border_dot = near_border and tiny_component and not touches_keep_box and not elongated_component
        if border_dot:
            cleaned[labels == label] = 0

    return cleaned


def _count_holes(binary: np.ndarray) -> int:
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return 0
    holes = 0
    for idx in range(len(contours)):
        parent = hierarchy[0][idx][3]
        if parent >= 0:
            holes += 1
    return holes


def _extract_shape_features(binary: np.ndarray) -> np.ndarray:
    if binary is None or binary.size == 0:
        return np.zeros((13,), dtype=np.float32)

    h, w = binary.shape[:2]
    total = float(max(h * w, 1))
    ink = float(cv2.countNonZero(binary))
    if ink <= 0:
        return np.zeros((13,), dtype=np.float32)

    ys, xs = np.where(binary > 0)
    x1 = int(xs.min())
    x2 = int(xs.max()) + 1
    y1 = int(ys.min())
    y2 = int(ys.max()) + 1
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    roi = binary[y1:y2, x1:x2]

    vert_splits = np.array_split(roi, 3, axis=0)
    hor_splits = np.array_split(roi, 3, axis=1)
    vert_density = [float(cv2.countNonZero(part)) / max(part.size, 1) for part in vert_splits]
    hor_density = [float(cv2.countNonZero(part)) / max(part.size, 1) for part in hor_splits]

    moments = cv2.moments(binary, binaryImage=True)
    cx = float(moments["m10"] / moments["m00"]) / max(w, 1) if moments["m00"] else 0.5
    cy = float(moments["m01"] / moments["m00"]) / max(h, 1) if moments["m00"] else 0.5
    holes = float(_count_holes(roi))

    return np.asarray(
        [
            ink / total,
            box_w / max(w, 1),
            box_h / max(h, 1),
            box_w / max(box_h, 1),
            cx,
            cy,
            *vert_density,
            *hor_density,
            holes,
        ],
        dtype=np.float32,
    )


def normalize_digit_crop(binary_image: np.ndarray, image_size: int = 32, margin: int = 4) -> np.ndarray:
    if binary_image is None or binary_image.size == 0:
        return np.zeros((image_size, image_size), dtype=np.uint8)

    if len(binary_image.shape) == 3:
        gray = cv2.cvtColor(binary_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = binary_image.copy()

    if gray.dtype != np.uint8:
        gray = gray.astype(np.uint8)

    if np.count_nonzero(gray) == 0:
        return np.zeros((image_size, image_size), dtype=np.uint8)

    if gray.mean() > 127:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    binary = _remove_border_dots(binary)

    points = cv2.findNonZero(binary)
    canvas = np.zeros((image_size, image_size), dtype=np.uint8)
    if points is None:
        return canvas

    x, y, w, h = cv2.boundingRect(points)
    roi = binary[y:y + h, x:x + w]
    target = image_size - (margin * 2)
    scale = min(target / max(w, 1), target / max(h, 1))
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = cv2.resize(roi, (new_w, new_h), interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC)
    x_off = (image_size - new_w) // 2
    y_off = (image_size - new_h) // 2
    canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
    return canvas


class HogFeatureExtractor:
    def __init__(
        self,
        image_size: int = 32,
        block_size: int = 8,
        block_stride: int = 4,
        cell_size: int = 4,
        bins: int = 9,
    ):
        self.image_size = image_size
        self.block_size = block_size
        self.block_stride = block_stride
        self.cell_size = cell_size
        self.bins = bins
        self.hog = cv2.HOGDescriptor(
            _winSize=(image_size, image_size),
            _blockSize=(block_size, block_size),
            _blockStride=(block_stride, block_stride),
            _cellSize=(cell_size, cell_size),
            _nbins=bins,
        )

    def compute(self, binary_image: np.ndarray) -> np.ndarray:
        normalized = normalize_digit_crop(binary_image, image_size=self.image_size)
        feature = self.hog.compute(normalized)
        if feature is None:
            return np.zeros((0,), dtype=np.float32)
        shape_feature = _extract_shape_features(normalized)
        return np.concatenate([feature.reshape(-1).astype(np.float32), shape_feature], axis=0)


class HogSvmEngine(BaseOcrEngine):
    def __init__(
        self,
        model_path: str,
        engine_name: str = "hog_svm",
        min_confidence: float = 0.45,
    ):
        super().__init__(engine_name=engine_name)
        self.model_path = Path(model_path).resolve()
        self.min_confidence = min_confidence
        self.enabled = False
        self.labels: List[str] = []
        self.classifier = None
        self.scaler = None
        self.extractor: Optional[HogFeatureExtractor] = None
        self._load()

    def _load(self) -> None:
        if not self.model_path.exists():
            logger.warning("HogSvmEngine: model not found: %s", self.model_path)
            return

        try:
            payload = joblib.load(self.model_path)
            self.labels = list(payload["labels"])
            self.classifier = payload["classifier"]
            self.scaler = payload["scaler"]
            self.extractor = HogFeatureExtractor(
                image_size=int(payload.get("image_size", 32)),
                block_size=int(payload.get("block_size", 8)),
                block_stride=int(payload.get("block_stride", 4)),
                cell_size=int(payload.get("cell_size", 4)),
                bins=int(payload.get("bins", 9)),
            )
            self.enabled = True
            logger.info("HogSvmEngine: loaded model %s with %d labels", self.model_path, len(self.labels))
        except Exception as exc:
            logger.error("HogSvmEngine: failed to load %s: %s", self.model_path, exc)
            self.enabled = False

    def recognize_cell(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        if not self.enabled or self.extractor is None or self.classifier is None or self.scaler is None:
            return []

        allowed = set(allowed_chars) if allowed_chars else set(self.labels)
        feature = self.extractor.compute(processed_image)
        if feature.size == 0:
            return []

        feature = self.scaler.transform([feature])
        probs = self.classifier.predict_proba(feature)[0]
        ranked = np.argsort(probs)[::-1]

        hypotheses: List[OcrHypothesis] = []
        for idx in ranked[:3]:
            label = self.labels[int(idx)]
            if label not in allowed:
                continue
            confidence = float(probs[int(idx)])
            if not hypotheses and confidence < self.min_confidence:
                return []
            hypotheses.append(OcrHypothesis(symbol=label, confidence=confidence, source=self.engine_name))
        return hypotheses

    def recognize_line(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        return []
