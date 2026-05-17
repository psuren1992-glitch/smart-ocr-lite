import json
import logging
from typing import Dict, List

import cv2
import numpy as np

from core.cell_shape_rules import CellShapeRules
from core.cell_classifier_flow import CellClassifierFlow
from core.digit_vote import DigitVoteHelper
from core.image_preprocessor import ImagePreprocessor
from core.interfaces.ocr_engine import BaseOcrEngine
from core.math_answer_rules import MathAnswerRules
from core.models.data_models import CellResult, OcrHypothesis
from core.ocr.line_recognizer import LineRecognizer
from core.row_answer_assembler import RowAnswerAssembler
from core.shape_rules_provider import ShapeRulesProvider

logger = logging.getLogger(__name__)


class SymbolClassifier:
    @staticmethod
    def _line_engine_priority(engine: BaseOcrEngine) -> tuple[int, str]:
        priority = {
            "google_docai": 0,
            "paddleocr": 1,
            "google_vision": 2,
            "tesseract": 3,
        }
        return (priority.get(engine.engine_name, 10), engine.engine_name)

    def __init__(
        self,
        engines: List[BaseOcrEngine],
        digit_vote_engines: List[BaseOcrEngine] | None = None,
        doubt_threshold: float = 0.65,
        handwritten_mode: bool = False,
    ):
        self.engines = engines
        self.digit_vote_engines = digit_vote_engines or engines
        self.doubt_threshold = doubt_threshold
        self.handwritten_mode = handwritten_mode

        self.preprocessor = ImagePreprocessor()
        self.shape_rules = CellShapeRules()
        self.shape_rules_provider = ShapeRulesProvider()
        self.math_answer_rules = MathAnswerRules()

        self.digit_vote = DigitVoteHelper(
            collect_hypotheses=self._collect_hypotheses,
            normalize_symbol=self._normalize_symbol,
            guess_digit_from_shape=self.shape_rules.guess_digit_from_shape,
        )
        self.cell_classifier_flow = CellClassifierFlow(
            engines=self.engines,
            handwritten_mode=self.handwritten_mode,
            doubt_threshold=self.doubt_threshold,
            shape_rules=self.shape_rules_provider,
            preprocessor=self.preprocessor,
            digit_vote_helper=self.digit_vote,
            classifier=self,
        )
        self.row_answer_assembler = RowAnswerAssembler(
            cell_classifier_flow=self.cell_classifier_flow,
            shape_rules=self.shape_rules,
            finalize_math_answer=self._finalize_math_answer,
            ai_row_reader=self.recognize_line,
        )
        self.line_recognizer = LineRecognizer(engines=sorted(self.engines, key=self._line_engine_priority))

    # ─── публичный API ───────────────────────────────────────────

    def classify(
        self,
        aligned_image: np.ndarray,
        cell: CellResult,
        allowed_chars: str = "0123456789-,.",
    ) -> None:
        self.cell_classifier_flow.classify(aligned_image, cell, allowed_chars=allowed_chars)

    def classify_row(
        self,
        aligned_image: np.ndarray,
        row_cells: list,
        allowed_chars: str = "0123456789-,.",
        row=None,
    ) -> str:
        return self.row_answer_assembler.classify_row(aligned_image, row_cells, row=row)

    def recognize_line(
        self,
        image: np.ndarray,
        bbox: tuple[int, int, int, int],
        allowed_chars: str = "",
        is_handwritten: bool = False,
    ) -> str:
        return self.line_recognizer.recognize(
            image,
            bbox,
            allowed_chars=allowed_chars,
            is_handwritten=is_handwritten,
        )

    # ─── внутренние делегаты (public по историческим причинам) ────

    def collect_hypotheses(
        self,
        processed_img: np.ndarray,
        allowed_chars: str = "0123456789-,.",
        is_handwritten: bool = False,
        engines=None,
    ):
        return self.cell_classifier_flow.collect_hypotheses(
            processed_img,
            allowed_chars=allowed_chars,
            is_handwritten=is_handwritten,
            engines=engines,
        )

    def _normalize_symbol(self, symbol: str) -> str:
        norm_map = {
            "I": "1",
            "l": "1",
            "|": "1",
            "i": "1",
            "O": "0",
            "o": "0",
            "Q": "0",
            "Z": "2",
            "z": "2",
            "S": "5",
            "s": "5",
            "B": "8",
            "G": "6",
            "T": "7",
            "'": ",",
            "`": ",",
            "´": ",",
            "ћ": "0",
            "ѕ": "0",
            "—": "3",
            "§": "4",
        }
        if len(symbol) == 1:
            return norm_map.get(symbol, symbol)
        return symbol

    def _finalize_math_answer(self, text: str, token_entries: list, filled_count: int) -> tuple[str, list[str]]:
        return self.math_answer_rules.finalize_math_answer(text, token_entries, filled_count)

    # ─── прокси для совместимости с training_dataset_builder ─────

    def _remove_dotted_cell_frame_for_row(self, binary: np.ndarray) -> np.ndarray:
        return self.shape_rules.remove_dotted_cell_frame_for_row(binary)

    def _preprocess_cell(self, aligned_image: np.ndarray, cell: CellResult) -> np.ndarray:
        return self.preprocessor.preprocess_cell(aligned_image, cell)

    # ─── приватные делегаты ──────────────────────────────────────

    def _collect_hypotheses(
        self,
        processed_img: np.ndarray,
        allowed_chars: str = "0123456789-,.",
        is_handwritten: bool = False,
        engines=None,
    ):
        return self.cell_classifier_flow.collect_hypotheses(
            processed_img,
            allowed_chars=allowed_chars,
            is_handwritten=is_handwritten,
            engines=engines,
        )

    def _log_doubt(self, cell: CellResult) -> None:
        if not cell.is_doubtful:
            return

        logger.debug(
            "DOUBT "
            + json.dumps(
                {
                    "cell": cell.cell_index,
                    "final": cell.best_symbol,
                    "confidence": round(cell.confidence, 3),
                    "reason": cell.doubt_reason,
                    "top3": [
                        {
                            "sym": hypothesis.symbol,
                            "conf": round(hypothesis.confidence, 3),
                            "src": hypothesis.source,
                        }
                        for hypothesis in (cell.top_candidates or [])[:3]
                    ],
                },
                ensure_ascii=False,
            )
        )

    def _make_digit_vote_candidates(
        self,
        standard_img: np.ndarray,
        row_img: np.ndarray,
        allowed_chars: str = "0123456789",
    ) -> List[OcrHypothesis]:
        return self.digit_vote.make_candidates(
            standard_img=standard_img,
            row_img=row_img,
            allowed_chars=allowed_chars,
            digit_vote_engines=self.digit_vote_engines,
        )

    def _select_voted_digit(
        self,
        candidates: List[OcrHypothesis],
        allowed_chars: str = "0123456789",
    ) -> str:
        return self.digit_vote.select_digit(candidates, allowed_chars=allowed_chars)

    def _guess_digit_from_shape(self, processed_img: np.ndarray) -> str:
        return self.shape_rules.guess_digit_from_shape(processed_img)
