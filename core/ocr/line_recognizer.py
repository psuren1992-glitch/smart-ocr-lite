import logging
from typing import List

import cv2
import numpy as np

from core.interfaces.ocr_engine import BaseOcrEngine
from core.models.data_models import OcrHypothesis

logger = logging.getLogger(__name__)


class LineRecognizer:
    """
    Выполняет распознавание строки текста (одной bounding box'овой области)
    с использованием подходящего OCR-движка, поддерживающего recognize_line.
    """

    def __init__(self, engines: List[BaseOcrEngine]):
        self.engines = engines

    def recognize(
        self,
        image: np.ndarray,
        bbox: tuple[int, int, int, int],
        allowed_chars: str = "",
        is_handwritten: bool = False,
    ) -> str:
        x1, y1, x2, y2 = bbox
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)
        if x2 <= x1 or y2 <= y1:
            return ""

        logger.debug(
            "LineRecognizer: bbox=%s engines=[%s]",
            bbox,
            [e.engine_name for e in self.engines],
        )
        crop = image[y1:y2, x1:x2]

        for engine in self.engines:
            if hasattr(engine, "recognize_line"):
                try:
                    try:
                        results = engine.recognize_line(
                            crop,
                            allowed_chars=allowed_chars,
                            is_handwritten=is_handwritten,
                        )
                    except TypeError:
                        results = engine.recognize_line(
                            crop, allowed_chars=allowed_chars
                        )

                    if results:
                        return results[0].symbol
                except Exception as e:
                    logger.error(
                        "LineRecognizer: engine %s error: %s",
                        engine.engine_name,
                        e,
                    )
        return ""
