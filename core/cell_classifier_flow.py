from typing import List

import cv2

from core.digit_vote import DigitVoteHelper
from core.image_preprocessor import ImagePreprocessor
from core.models.data_models import CellResult, OcrHypothesis
from core.shape_rules_provider import ShapeRulesProvider
from core.thresholds import CellFlowThresholds, get_thresholds


class CellClassifierFlow:
    def __init__(
        self,
        engines,
        handwritten_mode: bool,
        doubt_threshold: float,
        shape_rules,
        preprocessor,
        digit_vote_helper,
        *,
        classifier=None,
        thresholds: CellFlowThresholds | None = None,
    ):
        self.engines = engines
        self.handwritten_mode = handwritten_mode
        self.doubt_threshold = doubt_threshold
        self.shape_rules = shape_rules
        self.preprocessor = preprocessor
        self.digit_vote_helper = digit_vote_helper
        self.classifier = classifier
        self.t = thresholds or get_thresholds().cell_flow

    def _normalize_symbol(self, symbol: str) -> str:
        return self.classifier._normalize_symbol(symbol)

    def _log_doubt(self, cell: CellResult) -> None:
        self.classifier._log_doubt(cell)

    def collect_hypotheses(
        self,
        processed_img,
        allowed_chars: str = "0123456789-,.",
        is_handwritten: bool = False,
        engines=None,
    ):
        from core.models.data_models import OcrHypothesis

        hypotheses = []
        if processed_img is None or processed_img.size == 0 or cv2.countNonZero(processed_img) == 0:
            return hypotheses

        active_engines = engines or self.engines
        for engine in active_engines:
            try:
                engine_hypotheses = engine.recognize_cell(
                    processed_img,
                    allowed_chars=allowed_chars,
                    is_handwritten=is_handwritten,
                )
            except TypeError:
                engine_hypotheses = engine.recognize_cell(processed_img, allowed_chars=allowed_chars)

            hypotheses.extend(engine_hypotheses)

        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        return hypotheses

    def classify(self, aligned_image, cell: CellResult, allowed_chars: str = "0123456789-,.") -> None:
        t = self.t
        processed_img, meta = self._preprocess_cell_with_meta(aligned_image, cell)
        cell.is_crossed_out = meta.get("is_crossed_out", False)

        # 1. Проверка на метку (если в ячейке ожидается только отметка X)
        if "X" in allowed_chars.upper() and len(allowed_chars) <= 2:
            is_marked = self.shape_rules.looks_like_mark(processed_img)
            cell.best_symbol = "X" if is_marked else ""
            cell.confidence = t.marked_cell_confidence if is_marked else t.marked_cell_empty_confidence
            cell.is_empty = not is_marked
            cell.is_doubtful = False
            return

        if cv2.countNonZero(processed_img) == 0:
            empty = OcrHypothesis(symbol="", confidence=t.empty_cell_confidence, source="empty_cell")
            cell.best_symbol = ""
            cell.confidence = empty.confidence
            cell.top_candidates = [empty]
            cell.is_empty = True
            cell.is_doubtful = False
            cell.doubt_reason = "crossed_out" if cell.is_crossed_out else ""
            return

        all_hypotheses: List[OcrHypothesis] = self.collect_hypotheses(
            processed_img,
            allowed_chars=allowed_chars,
            is_handwritten=self.handwritten_mode,
            engines=self.engines,
        )
        cell.is_doubtful = False
        cell.doubt_reason = ""
        row_processed_img = self.preprocess_cell_for_row(aligned_image, cell)

        # Early break on empty — если первый engine вернул пустой символ с высокой уверенностью,
        # дальше не идём (collect_hypotheses уже собрал всё; тут фильтруем пост-фактум)
        if all_hypotheses and all_hypotheses[0].symbol == "" and all_hypotheses[0].confidence > t.empty_early_break_confidence:
            pass  # продолжаем — hybrid_digit ниже не сработает, и сработает empty-логика

        if not self.shape_rules.looks_like_minus(row_processed_img) and not self.shape_rules.looks_like_comma(row_processed_img):
            hybrid_digit = self._classify_digit_cell(processed_img, row_processed_img, allowed_chars="0123456789")
            if hybrid_digit:
                all_hypotheses.append(
                    OcrHypothesis(
                        symbol=hybrid_digit,
                        confidence=t.hybrid_digit_confidence,
                        source="hybrid_digit_vote",
                    )
                )

        if not all_hypotheses:
            cell.is_doubtful = True
            cell.doubt_reason = "No hypotheses generated"
            self._log_doubt(cell)
            return

        all_hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        top_candidates = all_hypotheses[:t.top_candidates_count]
        best_hypothesis = top_candidates[0]

        raw_symbol = best_hypothesis.symbol
        cell.best_symbol = self._normalize_symbol(raw_symbol)
        cell.confidence = best_hypothesis.confidence
        cell.top_candidates = top_candidates
        cell.is_empty = (cell.best_symbol == "")

        if not cell.is_empty and cell.confidence < self.doubt_threshold:
            cell.is_doubtful = True
            cell.doubt_reason = f"Low confidence ({cell.confidence:.2f})"
        elif len(top_candidates) > 1:
            distinct_candidates = []
            seen_symbols = set()
            for candidate in top_candidates:
                normalized_symbol = self._normalize_symbol(candidate.symbol)
                if normalized_symbol in seen_symbols:
                    continue
                seen_symbols.add(normalized_symbol)
                distinct_candidates.append(candidate)

            if len(distinct_candidates) > 1 and not cell.is_empty:
                diff = distinct_candidates[0].confidence - distinct_candidates[1].confidence
                cell.is_doubtful = True
                if diff < t.close_candidate_diff:
                    cell.doubt_reason = (
                        f"Close candidates: {distinct_candidates[0].symbol} vs {distinct_candidates[1].symbol}"
                    )
                else:
                    cell.is_doubtful = False
                    cell.doubt_reason = ""

        self._log_doubt(cell)

    def preprocess_cell(self, image, cell):
        """Публичная обёртка над preprocess_cell_with_meta — возвращает только бинарную матрицу."""
        processed_img, _ = self._preprocess_cell_with_meta(image, cell)
        return processed_img

    def preprocess_cell_for_row(self, image, cell):
        """Бинаризует ячейку для row-анализа (рукописный режим)."""
        x1, y1, x2, y2 = cell.inner_bbox
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)

        if x2 <= x1 or y2 <= y1:
            import numpy as np
            return np.zeros((10, 10), dtype=np.uint8)

        crop = image[y1:y2, x1:x2]
        if len(crop.shape) == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        else:
            gray = crop.copy()

        binary = self.preprocessor.binarize_for_ocr(gray, is_handwritten=True)
        if self.shape_rules.is_crossed_out_pattern(binary):
            import numpy as np
            return np.zeros_like(binary)
        return self.shape_rules.remove_dotted_cell_frame_for_row(binary)

    def _preprocess_cell_with_meta(self, image, cell):
        """Извлекает и бинаризует ячейку, возвращает мета-информацию."""
        x1, y1, x2, y2 = cell.inner_bbox
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)

        if x2 <= x1 or y2 <= y1:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Empty bbox for cell {cell.cell_index}")
            import numpy as np
            return np.zeros((10, 10), dtype=np.uint8), {"is_crossed_out": False}

        crop = image[y1:y2, x1:x2]
        if len(crop.shape) == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        else:
            gray = crop.copy()

        binary = self.preprocessor.binarize_for_ocr(gray, is_handwritten=self.handwritten_mode)
        if self.shape_rules.is_crossed_out_pattern(binary):
            import numpy as np
            return np.zeros_like(binary), {"is_crossed_out": True}

        return self.shape_rules.remove_dotted_cell_frame(binary), {"is_crossed_out": False}

    def _classify_digit_cell(self, standard_img, row_img, allowed_chars="0123456789"):
        """Голосование цифр через DigitVoteHelper."""
        candidates = self.digit_vote_helper.make_candidates(
            standard_img=standard_img,
            row_img=row_img,
            allowed_chars=allowed_chars,
            digit_vote_engines=self.engines,
        )
        return self.digit_vote_helper.select_digit(candidates, allowed_chars=allowed_chars)
