import logging
import os
from typing import List, Optional

import cv2
import numpy as np

from core.interfaces.ocr_engine import BaseOcrEngine
from core.models.data_models import OcrHypothesis
from core.ocr.hog_svm_engine import normalize_digit_crop

logger = logging.getLogger(__name__)


class PaddleOcrEngine(BaseOcrEngine):
    def __init__(
        self,
        lang: str = "eslav",
        model_name: str = "eslav_PP-OCRv5_mobile_rec",
        engine_name: str = "paddleocr",
        min_confidence: float = 0.50,
        disable_source_check: bool = True,
    ):
        super().__init__(engine_name=engine_name)
        self.lang = lang
        self.model_name = model_name
        self.min_confidence = min_confidence
        self.disable_source_check = disable_source_check
        self._recognizer = None
        self.enabled = False
        self._init_error: Optional[str] = None

    def _normalize_symbol(self, text: str, allowed_chars: str) -> str:
        if not text:
            return ""

        # Step 1: унификация кириллических вариантов
        cyrillic_fixes = {
            "Ё": "Е",
            "ё": "е",
            "є": "е",
            "і": "и",
            "ї": "и",
            "ў": "у",
            "ґ": "г",
            "’": "'",
        }

        alias_map = {
            # Digits
            "O": "0",
            "o": "0",
            "Q": "0",
            "I": "1",
            "l": "1",
            "i": "1",
            "|": "1",
            "Z": "2",
            "z": "2",
            "S": "5",
            "s": "5",
            "G": "6",
            "C": "6",
            "T": "7",
            "B": "8",
            # Latin to Cyrillic (common confusions)
            "A": "А",
            "E": "Е",
            "K": "К",
            "M": "М",
            "H": "Н",
            "P": "Р",
            "X": "Х",
            "y": "У",
            "R": "Р",
            "V": "В",
            "L": "Л",
            "a": "а",
            "e": "е",
            "c": "с",
        }
        allowed_set = set(allowed_chars or "")
        is_digit_only = bool(allowed_set) and allowed_set.issubset(set("0123456789-,."))

        if not is_digit_only:
            # Overwrite digit mappings for text mode
            alias_map["C"] = "С"
            alias_map["T"] = "Т"
            alias_map["B"] = "В"
            alias_map["O"] = "О"
            alias_map["o"] = "о"
            alias_map["c"] = "с"

        # Применяем оба маппинга
        text = "".join(cyrillic_fixes.get(ch, ch) for ch in text.strip())
        normalized = "".join(alias_map.get(ch, ch) for ch in text)

        if not allowed_chars:
            return normalized
        return "".join(ch for ch in normalized if ch in allowed_chars)

    def _ensure_model(self) -> bool:
        if self.enabled and self._recognizer is not None:
            return True
        if self._init_error:
            return False

        try:
            if self.disable_source_check:
                os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddleocr import TextRecognition

            self._recognizer = TextRecognition(model_name=self.model_name)
            self.enabled = True
            logger.info(
                "PaddleOcrEngine initialized: model=%s lang=%s",
                self.model_name,
                self.lang,
            )
            return True
        except Exception as exc:
            self._init_error = str(exc)
            self.enabled = False
            logger.error("PaddleOcrEngine initialization failed: %s", exc)
            return False

    def _prepare_image(self, processed_image: np.ndarray, allowed_chars: str = "") -> Optional[np.ndarray]:
        if processed_image is None or processed_image.size == 0:
            return None

        if len(processed_image.shape) == 2:
            gray = processed_image
        else:
            gray = cv2.cvtColor(processed_image, cv2.COLOR_BGR2GRAY)

        if cv2.countNonZero(gray) == 0:
            return None

        allowed_set = set(allowed_chars or "")
        digit_only_mode = bool(allowed_set) and allowed_set.issubset(set("0123456789"))

        if digit_only_mode:
            # Для цифр используем специальную нормализацию (центрирование)
            # PaddleOCR любит светлый фон — инвертируем если надо
            avg_brightness = np.mean(gray)
            if avg_brightness < 127:
                prepared = cv2.bitwise_not(gray)
            else:
                prepared = gray

            centered = normalize_digit_crop(prepared, image_size=48, margin=6)
            # normalize_digit_crop возвращает светлые чернила на тёмном фоне
            # Инвертируем обратно для Paddle
            normalized = cv2.bitwise_not(centered)
            normalized = cv2.copyMakeBorder(
                normalized,
                top=18,
                bottom=18,
                left=18,
                right=18,
                borderType=cv2.BORDER_CONSTANT,
                value=255,
            )
            scaled = cv2.resize(normalized, (144, 144), interpolation=cv2.INTER_CUBIC)
        else:
            # Для текста (русский, ФИО) — НЕ инвертируем, оставляем как есть.
            # PaddleOCR обучен на естественных документах (тёмный текст на светлом фоне).
            # Инверсия по средней яркости только вредит рукописному тексту.
            # Добавляем поля и увеличиваем для лучшего распознавания мелкого почерка.
            normalized = cv2.copyMakeBorder(
                gray,
                top=20,
                bottom=20,
                left=20,
                right=20,
                borderType=cv2.BORDER_CONSTANT,
                value=255,
            )
            # Масштаб ×2 вместо ×3 — слишком большое увеличение для рукописного
            # текста размывает штрихи и снижает качество распознавания
            scaled = cv2.resize(normalized, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

        return cv2.cvtColor(scaled, cv2.COLOR_GRAY2BGR)

    def _filter_text(self, text: str, allowed_chars: str) -> str:
        raw = self._normalize_symbol((text or "").strip(), allowed_chars)
        if not allowed_chars:
            return raw
        return "".join(ch for ch in raw if ch in allowed_chars)

    def recognize_cell(self, processed_image: np.ndarray, allowed_chars: str = "0123456789-,.") -> List[OcrHypothesis]:
        if not self._ensure_model():
            return []

        prepared = self._prepare_image(processed_image, allowed_chars=allowed_chars)
        if prepared is None:
            return []

        try:
            result = self._recognizer.predict(prepared)
        except Exception as exc:
            logger.error("PaddleOcrEngine cell recognition failed: %s", exc)
            return []

        if not result:
            return []

        item = result[0]
        text = self._filter_text(item.get("rec_text", ""), allowed_chars)
        confidence = float(item.get("rec_score", 0.0) or 0.0)

        if len(text) != 1 or confidence < self.min_confidence:
            return []

        return [OcrHypothesis(symbol=text, confidence=confidence, source=self.engine_name)]

    def recognize_line(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        if not self._ensure_model():
            return []

        prepared = self._prepare_image(processed_image, allowed_chars=allowed_chars)
        if prepared is None:
            return []

        try:
            result = self._recognizer.predict(prepared)
        except Exception as exc:
            logger.error("PaddleOcrEngine line recognition failed: %s", exc)
            return []

        if not result:
            return []

        item = result[0]
        raw_text = item.get("rec_text", "")
        confidence = float(item.get("rec_score", 0.0) or 0.0)
        logger.info(f"PaddleOCR line raw: '{raw_text}' confidence={confidence:.3f}")

        text = self._filter_text(raw_text, allowed_chars)

        # Постпроцессинг: схлопываем множественные пробелы, обрезаем
        text = " ".join(text.split())

        # Для строк (ФИО, сложный рукописный текст) используем умеренный порог
        # Если confidence < 0.30 — почти наверняка мусор
        line_threshold = 0.30
        if not text or confidence < line_threshold:
            logger.info(f"PaddleOCR line filtered: '{text}' conf={confidence:.3f} < {line_threshold}")
            return []

        return [OcrHypothesis(symbol=text, confidence=confidence, source=f"{self.engine_name}_line")]
