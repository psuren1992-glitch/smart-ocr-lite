import logging
from typing import List

import cv2
import numpy as np

from core.interfaces.ocr_engine import BaseOcrEngine
from core.models.data_models import OcrHypothesis

logger = logging.getLogger(__name__)


class DigitEngine(BaseOcrEngine):
    def __init__(self, engine_name: str = "digit_engine"):
        super().__init__(engine_name=engine_name)
        self.canvas_size = 32
        self.margin = 4
        self.min_foreground_ratio = 0.02
        self.max_foreground_ratio = 0.75
        self.min_confidence = 0.68
        self.min_shape_score = 0.58
        self.min_margin = 0.10
        self.templates = self._build_templates()

    def _augment_binary(
        self,
        binary: np.ndarray,
        shear_x: float = 0.0,
        tilt_deg: float = 0.0,
    ) -> np.ndarray:
        h, w = binary.shape[:2]
        augmented = binary.copy()

        if abs(shear_x) > 1e-6:
            shear_matrix = np.array(
                [[1.0, shear_x, -shear_x * w * 0.5], [0.0, 1.0, 0.0]],
                dtype=np.float32,
            )
            augmented = cv2.warpAffine(
                augmented,
                shear_matrix,
                (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=0,
            )

        if abs(tilt_deg) > 1e-6:
            center = (w / 2.0, h / 2.0)
            rot_matrix = cv2.getRotationMatrix2D(center, tilt_deg, 1.0)
            augmented = cv2.warpAffine(
                augmented,
                rot_matrix,
                (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=0,
            )

        return cv2.threshold(augmented, 127, 255, cv2.THRESH_BINARY)[1]

    def _draw_manual_digit(self, digit: str) -> list[np.ndarray]:
        variants: list[np.ndarray] = []
        canvas = np.zeros((self.canvas_size, self.canvas_size), dtype=np.uint8)

        if digit == "1":
            cv2.line(canvas, (16, 6), (12, 11), 255, 2, cv2.LINE_AA)
            cv2.line(canvas, (12, 11), (16, 27), 255, 3, cv2.LINE_AA)
            cv2.line(canvas, (9, 27), (20, 27), 255, 2, cv2.LINE_AA)
            variants.append(self._normalize_binary(canvas))

            canvas_long_serif = np.zeros((self.canvas_size, self.canvas_size), dtype=np.uint8)
            cv2.line(canvas_long_serif, (16, 6), (16, 28), 255, 2, cv2.LINE_AA)
            cv2.line(canvas_long_serif, (10, 6), (16, 6), 255, 2, cv2.LINE_AA)
            cv2.line(canvas_long_serif, (12, 28), (20, 28), 255, 2, cv2.LINE_AA)
            variants.append(self._normalize_binary(canvas_long_serif))

            canvas_slanted = np.zeros((self.canvas_size, self.canvas_size), dtype=np.uint8)
            cv2.line(canvas_slanted, (17, 6), (15, 28), 255, 2, cv2.LINE_AA)
            cv2.line(canvas_slanted, (11, 9), (17, 6), 255, 2, cv2.LINE_AA)
            variants.append(self._normalize_binary(canvas_slanted))

            canvas_diagonal = np.zeros((self.canvas_size, self.canvas_size), dtype=np.uint8)
            cv2.line(canvas_diagonal, (18, 4), (14, 28), 255, 2, cv2.LINE_AA)
            cv2.line(canvas_diagonal, (12, 8), (18, 4), 255, 2, cv2.LINE_AA)
            variants.append(self._normalize_binary(canvas_diagonal))

            canvas_straight_school = np.zeros((self.canvas_size, self.canvas_size), dtype=np.uint8)
            cv2.line(canvas_straight_school, (17, 6), (14, 10), 255, 2, cv2.LINE_AA)
            cv2.line(canvas_straight_school, (14, 10), (14, 28), 255, 3, cv2.LINE_AA)
            cv2.line(canvas_straight_school, (10, 28), (18, 28), 255, 2, cv2.LINE_AA)
            variants.append(self._normalize_binary(canvas_straight_school))
        elif digit == "7":
            cv2.line(canvas, (7, 8), (25, 8), 255, 3, cv2.LINE_AA)
            cv2.line(canvas, (24, 8), (12, 27), 255, 3, cv2.LINE_AA)
            cv2.line(canvas, (11, 17), (20, 17), 255, 2, cv2.LINE_AA)
            variants.append(self._normalize_binary(canvas))

            canvas_crossbar = np.zeros((self.canvas_size, self.canvas_size), dtype=np.uint8)
            cv2.line(canvas_crossbar, (6, 8), (25, 8), 255, 3, cv2.LINE_AA)
            cv2.line(canvas_crossbar, (24, 8), (13, 28), 255, 3, cv2.LINE_AA)
            cv2.line(canvas_crossbar, (10, 18), (20, 18), 255, 2, cv2.LINE_AA)
            variants.append(self._normalize_binary(canvas_crossbar))

            canvas_heavy_crossbar = np.zeros((self.canvas_size, self.canvas_size), dtype=np.uint8)
            cv2.line(canvas_heavy_crossbar, (7, 7), (25, 7), 255, 3, cv2.LINE_AA)
            cv2.line(canvas_heavy_crossbar, (24, 7), (14, 28), 255, 3, cv2.LINE_AA)
            cv2.line(canvas_heavy_crossbar, (11, 16), (21, 16), 255, 3, cv2.LINE_AA)
            variants.append(self._normalize_binary(canvas_heavy_crossbar))
        return [variant for variant in variants if cv2.countNonZero(variant) > 0]

    def _build_templates(self) -> dict[str, list[np.ndarray]]:
        templates: dict[str, list[np.ndarray]] = {str(d): [] for d in range(10)}
        fonts = [
            cv2.FONT_HERSHEY_SIMPLEX,
            cv2.FONT_HERSHEY_DUPLEX,
        ]
        scales = [1.0]
        thicknesses = [1, 2]
        shears = [0.0, -0.1, 0.1]
        tilts = [0.0, -5.0, 5.0]

        for digit in templates.keys():
            seen: set[bytes] = set()

            for manual_variant in self._draw_manual_digit(digit):
                template_key = manual_variant.tobytes()
                if template_key not in seen:
                    seen.add(template_key)
                    templates[digit].append(manual_variant)

            for font in fonts:
                for scale in scales:
                    for thickness in thicknesses:
                        canvas = np.full((self.canvas_size, self.canvas_size), 255, dtype=np.uint8)
                        text_size, baseline = cv2.getTextSize(digit, font, scale, thickness)
                        x = max(0, (self.canvas_size - text_size[0]) // 2)
                        y = max(text_size[1], (self.canvas_size + text_size[1]) // 2)
                        cv2.putText(canvas, digit, (x, y), font, scale, 0, thickness, cv2.LINE_AA)
                        base_binary = cv2.threshold(canvas, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

                        for shear_x in shears:
                            for tilt_deg in tilts:
                                if shear_x != 0.0 and abs(tilt_deg) > 4.0:
                                    continue
                                augmented = self._augment_binary(
                                    base_binary,
                                    shear_x=shear_x,
                                    tilt_deg=tilt_deg,
                                )
                                normalized = self._normalize_binary(augmented)
                                if cv2.countNonZero(normalized) == 0:
                                    continue
                                template_key = normalized.tobytes()
                                if template_key in seen:
                                    continue
                                seen.add(template_key)
                                templates[digit].append(normalized)
        return templates

    def _normalize_binary(self, binary: np.ndarray) -> np.ndarray:
        points = cv2.findNonZero(binary)
        canvas = np.zeros((self.canvas_size, self.canvas_size), dtype=np.uint8)
        if points is None:
            return canvas

        x, y, w, h = cv2.boundingRect(points)
        roi = binary[y:y + h, x:x + w]
        target = self.canvas_size - (self.margin * 2)
        scale = min(target / max(w, 1), target / max(h, 1))
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        resized = cv2.resize(roi, (new_w, new_h), interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC)
        x_off = (self.canvas_size - new_w) // 2
        y_off = (self.canvas_size - new_h) // 2
        canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
        return (canvas > 0).astype(np.uint8) * 255

    def _component_count(self, binary: np.ndarray) -> int:
        num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        count = 0
        for idx in range(1, num_labels):
            area = stats[idx, cv2.CC_STAT_AREA]
            if area >= 8:
                count += 1
        return count

    def _prepare_digit_candidate(self, processed_image: np.ndarray) -> np.ndarray | None:
        ratio = float(cv2.countNonZero(processed_image)) / float(processed_image.size) if processed_image.size else 0.0
        if ratio < self.min_foreground_ratio or ratio > self.max_foreground_ratio:
            return None

        binary = (processed_image > 0).astype(np.uint8) * 255
        if self._component_count(binary) > 3:
            return None

        normalized = self._normalize_binary(binary)
        if cv2.countNonZero(normalized) == 0:
            return None
        return normalized

    def _score_template(self, candidate: np.ndarray, template: np.ndarray) -> float:
        cand_bool = candidate > 0
        templ_bool = template > 0
        intersection = float(np.logical_and(cand_bool, templ_bool).sum())
        union = float(np.logical_or(cand_bool, templ_bool).sum())
        if union <= 0:
            return 0.0
        iou = intersection / union

        cand_m = cv2.moments(candidate)
        templ_m = cv2.moments(template)
        cand_h = cv2.HuMoments(cand_m).flatten()
        templ_h = cv2.HuMoments(templ_m).flatten()
        cand_h = -np.sign(cand_h) * np.log10(np.abs(cand_h) + 1e-12)
        templ_h = -np.sign(templ_h) * np.log10(np.abs(templ_h) + 1e-12)
        hu_dist = float(np.linalg.norm(cand_h - templ_h))
        hu_score = 1.0 / (1.0 + hu_dist)
        return (iou * 0.7) + (hu_score * 0.3)

    def recognize_cell(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        if allowed_chars and not any(ch.isdigit() for ch in allowed_chars):
            return []

        candidate = self._prepare_digit_candidate(processed_image)
        if candidate is None:
            return []

        best_scores: list[tuple[str, float]] = []
        for digit, variants in self.templates.items():
            score = max(self._score_template(candidate, template) for template in variants)
            best_scores.append((digit, score))

        best_scores.sort(key=lambda item: item[1], reverse=True)
        if not best_scores:
            return []

        best_digit, best_score = best_scores[0]
        second_score = best_scores[1][1] if len(best_scores) > 1 else 0.0
        margin = best_score - second_score
        confidence = max(0.0, min(0.99, (best_score * 0.75) + ((best_score - second_score) * 0.8)))

        if confidence < self.min_confidence or best_score < self.min_shape_score or margin < self.min_margin:
            return []

        hypotheses = [OcrHypothesis(symbol=best_digit, confidence=confidence, source=self.engine_name)]
        if len(best_scores) > 1 and second_score >= self.min_confidence - 0.08:
            second_digit, _ = best_scores[1]
            second_conf = max(0.0, min(confidence - 0.01, second_score * 0.7))
            hypotheses.append(OcrHypothesis(symbol=second_digit, confidence=second_conf, source=f"{self.engine_name}_alt"))
        return hypotheses

    def recognize_line(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        return []
