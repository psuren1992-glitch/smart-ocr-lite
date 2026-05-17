import cv2
import numpy as np
import pytesseract
from typing import Callable, Dict, List

import numpy as np

from core.models.data_models import OcrHypothesis
from core.thresholds import DigitVoteThresholds, get_thresholds


class DigitVoteHelper:
    @staticmethod
    def tesseract_single_char(processed_img: np.ndarray, allowed_chars: str, psm: int) -> str:
        """Статический утилитарный метод: опрос Tesseract с заданным PSM для одной ячейки."""
        if processed_img is None or processed_img.size == 0 or cv2.countNonZero(processed_img) == 0:
            return ""

        h, w = processed_img.shape[:2]
        target_h = 96
        if h != target_h:
            scale = target_h / max(1, h)
            new_w = max(1, int(w * scale))
            processed_img = cv2.resize(processed_img, (new_w, target_h), interpolation=cv2.INTER_CUBIC)
            _, processed_img = cv2.threshold(processed_img, 127, 255, cv2.THRESH_BINARY)

        inv = cv2.bitwise_not(processed_img)
        padded = cv2.copyMakeBorder(inv, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        config = f"--psm {psm} --oem 1 -l eng -c tessedit_char_whitelist={allowed_chars}"
        try:
            text = pytesseract.image_to_string(padded, config=config)
        except Exception:
            return ""
        text = "".join(ch for ch in text.strip().replace("\n", "").replace(" ", "") if ch in allowed_chars)
        return text[:1]

    def __init__(
        self,
        collect_hypotheses: Callable,
        normalize_symbol: Callable[[str], str],
        guess_digit_from_shape: Callable[[np.ndarray], str],
        thresholds: DigitVoteThresholds | None = None,
    ):
        self.collect_hypotheses = collect_hypotheses
        self.normalize_symbol = normalize_symbol
        self.guess_digit_from_shape = guess_digit_from_shape
        self.t = thresholds or get_thresholds().digit_vote

    def source_vote_weight(self, source: str) -> float:
        t = self.t
        if source.startswith("paddleocr"):
            return t.paddleocr_weight
        if source.startswith("hog_svm"):
            return t.hog_svm_weight
        if source.startswith("digit_engine"):
            return t.digit_engine_weight
        if source.startswith("shape_agree"):
            return t.shape_agree_weight
        if source.startswith("shape_row"):
            return t.shape_row_weight
        if source.startswith("shape_standard"):
            return t.shape_standard_weight
        if source.startswith("tesseract_psm8") or source.startswith("tesseract_psm13"):
            return t.tesseract_psm8_13_weight
        if source.startswith("tesseract_psm10"):
            return t.tesseract_psm10_weight
        if source.startswith("tesseract"):
            return t.tesseract_cell_weight
        return t.default_weight

    def source_vote_group(self, source: str) -> str:
        if source.startswith("paddleocr"):
            return "paddleocr_row" if source.endswith("_row") else "paddleocr_standard"
        if source.startswith("hog_svm"):
            return "hog_svm_row" if source.endswith("_row") else "hog_svm_standard"
        if source.startswith("digit_engine"):
            return "digit_engine_row" if source.endswith("_row") else "digit_engine_standard"
        if source.startswith("tesseract_psm"):
            return "tesseract_psm_row" if source.endswith("_row") else "tesseract_psm_standard"
        if source.startswith("tesseract"):
            return "tesseract_cell_row" if source.endswith("_row") else "tesseract_cell_standard"
        return source

    def make_candidates(
        self,
        standard_img: np.ndarray,
        row_img: np.ndarray,
        allowed_chars: str,
        digit_vote_engines: list,
    ) -> List[OcrHypothesis]:
        t = self.t
        candidates: List[OcrHypothesis] = []

        for label, processed_img in [("row", row_img), ("standard", standard_img)]:
            hypotheses = self.collect_hypotheses(
                processed_img,
                allowed_chars=allowed_chars,
                is_handwritten=False,
                engines=digit_vote_engines,
            )
            for hypothesis in hypotheses:
                symbol = self.normalize_symbol(hypothesis.symbol)
                if len(symbol) == 1 and symbol in allowed_chars:
                    candidates.append(
                        OcrHypothesis(
                            symbol=symbol,
                            confidence=hypothesis.confidence,
                            source=f"{hypothesis.source}_{label}",
                        )
                    )

        for label, processed_img in [("row", row_img), ("standard", standard_img)]:
            # Check if tesseract is enabled before running PSM loops
            tess_engine = next((e for e in digit_vote_engines if getattr(e, "engine_name", "") == "tesseract"), None)
            if tess_engine and not getattr(tess_engine, "enabled", True):
                continue

            for psm, confidence in [(8, t.psm8_confidence), (13, t.psm13_confidence), (10, t.psm10_confidence)]:
                symbol = DigitVoteHelper.tesseract_single_char(processed_img, allowed_chars=allowed_chars, psm=psm)
                if symbol and symbol in allowed_chars:
                    candidates.append(
                        OcrHypothesis(
                            symbol=symbol,
                            confidence=confidence,
                            source=f"tesseract_psm{psm}_{label}",
                        )
                    )

        row_shape = self.guess_digit_from_shape(row_img)
        standard_shape = self.guess_digit_from_shape(standard_img)
        if row_shape:
            candidates.append(OcrHypothesis(symbol=row_shape, confidence=t.shape_row_confidence, source="shape_row"))
        if standard_shape:
            candidates.append(OcrHypothesis(symbol=standard_shape, confidence=t.shape_standard_confidence, source="shape_standard"))
        if row_shape and standard_shape and row_shape == standard_shape:
            candidates.append(OcrHypothesis(symbol=row_shape, confidence=t.shape_agree_confidence, source="shape_agree"))

        return candidates

    def select_digit(
        self,
        candidates: List[OcrHypothesis],
        allowed_chars: str,
    ) -> str:
        if not candidates:
            return ""

        t = self.t
        grouped_totals: Dict[str, Dict[str, float]] = {}
        max_confidences: Dict[str, float] = {}

        for hypothesis in candidates:
            symbol = self.normalize_symbol(hypothesis.symbol)
            if len(symbol) != 1 or symbol not in allowed_chars:
                continue

            weighted_score = max(0.01, hypothesis.confidence) * self.source_vote_weight(hypothesis.source)
            group = self.source_vote_group(hypothesis.source)
            symbol_groups = grouped_totals.setdefault(symbol, {})
            symbol_groups[group] = max(symbol_groups.get(group, 0.0), weighted_score)
            max_confidences[symbol] = max(max_confidences.get(symbol, 0.0), hypothesis.confidence)

        totals = {symbol: sum(groups.values()) for symbol, groups in grouped_totals.items()}
        if not totals:
            return ""

        ranked = sorted(
            totals.items(),
            key=lambda item: (item[1], max_confidences.get(item[0], 0.0)),
            reverse=True,
        )
        best_symbol, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        best_conf = max_confidences.get(best_symbol, 0.0)

        if len(ranked) > 1:
            alt_symbol, alt_score = ranked[1]
            best_groups = set(grouped_totals.get(best_symbol, {}).keys())
            alt_groups = set(grouped_totals.get(alt_symbol, {}).keys())
            best_is_tesseract_only = best_groups and all(group.startswith("tesseract") for group in best_groups)
            alt_has_shape = any(group.startswith("shape") for group in alt_groups)
            if (
                best_is_tesseract_only
                and alt_has_shape
                and alt_score >= best_score * t.alt_score_min_ratio
                and max_confidences.get(alt_symbol, 0.0) >= t.alt_conf_min
            ):
                return alt_symbol

        if best_score < t.low_score_threshold and best_conf < t.low_conf_threshold:
            return ""
        if (best_score - second_score) < t.close_vote_diff and best_conf < t.close_conf_threshold:
            return ""

        return best_symbol
