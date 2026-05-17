import cv2
import numpy as np
import pytesseract
import logging
from typing import List
from core.interfaces.ocr_engine import BaseOcrEngine
from core.models.data_models import OcrHypothesis

logger = logging.getLogger(__name__)


class TesseractEngine(BaseOcrEngine):
    def __init__(self, tesseract_cmd: str = None, engine_name: str = "tesseract"):
        super().__init__(engine_name=engine_name)
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        self.enabled = True
        try:
            pytesseract.get_tesseract_version()
        except Exception as e:
            logger.error(f"Tesseract не найден или не работает: {e}. Engine '{engine_name}' будет отключен.")
            self.enabled = False

        if self.enabled:
            self._rus_available = self._check_language("rus")
            self._eng_available = self._check_language("eng")
            if not self._rus_available:
                logger.warning(
                    "Языковой пакет 'rus' для Tesseract не установлен! "
                    "Рукописные русские ответы будут распознаваться хуже. "
                    "Установите: sudo apt-get install tesseract-ocr-rus  "
                    "или скачайте tessdata с https://github.com/tesseract-ocr/tessdata_best"
                )
        else:
            self._rus_available = False
            self._eng_available = False

    def _check_language(self, lang: str) -> bool:
        if not self.enabled:
            return False
        try:
            langs = pytesseract.get_languages()
            return lang in langs
        except Exception:
            return False

    def _prepare_image_for_tesseract(
        self,
        binary_cell: np.ndarray,
        pad_size: int = 20,
        scale_to_height: int = 96,
    ) -> np.ndarray:
        """
        Готовит бинарное изображение (чернила=255, фон=0) для Tesseract.
        Масштабирует до нужной высоты и инвертирует (Tesseract хочет тёмный текст на светлом фоне).
        """
        if binary_cell is None or binary_cell.size == 0:
            return np.full((scale_to_height, scale_to_height), 255, dtype=np.uint8)

        h, w = binary_cell.shape[:2]
        if h < scale_to_height:
            scale = scale_to_height / h
            new_w = max(1, int(w * scale))
            binary_cell = cv2.resize(
                binary_cell, (new_w, scale_to_height), interpolation=cv2.INTER_CUBIC
            )
            _, binary_cell = cv2.threshold(binary_cell, 127, 255, cv2.THRESH_BINARY)

        inv_img = cv2.bitwise_not(binary_cell)
        padded = cv2.copyMakeBorder(
            inv_img,
            top=pad_size, bottom=pad_size, left=pad_size, right=pad_size,
            borderType=cv2.BORDER_CONSTANT,
            value=255,
        )
        return padded

    def _build_lang_string(self, need_cyrillic: bool) -> str:
        langs = []
        if need_cyrillic and self._rus_available:
            langs.append("rus")
        if self._eng_available:
            langs.append("eng")
        return "+".join(langs) if langs else "eng"

    def recognize_cell(
        self,
        processed_image: np.ndarray,
        allowed_chars: str = "0123456789-,.",
        is_handwritten: bool = False,
    ) -> List[OcrHypothesis]:
        """
        Распознаёт одиночный символ/слово в клетке.
        is_handwritten=True — включает русский язык и psm 8 (одно слово).
        """
        if not self.enabled:
            return []

        hypotheses = []
        tess_img = self._prepare_image_for_tesseract(processed_image, pad_size=20, scale_to_height=96)

        if is_handwritten:
            lang = self._build_lang_string(need_cyrillic=True)
            # psm 8 — одно слово; oem 1 — LSTM нейросеть (лучше для рукописи)
            config = f"--psm 8 --oem 1 -l {lang}"
        else:
            lang = self._build_lang_string(need_cyrillic=False)
            if allowed_chars:
                config = f"--psm 10 --oem 1 -l {lang} -c tessedit_char_whitelist={allowed_chars}"
            else:
                config = f"--psm 10 --oem 1 -l {lang}"

        try:
            data = pytesseract.image_to_data(
                tess_img, config=config, output_type=pytesseract.Output.DICT
            )
            best_symbol = ""
            best_conf = -1.0

            for i, text in enumerate(data["text"]):
                text = text.strip()
                if text:
                    conf = float(data["conf"][i]) / 100.0
                    if conf > best_conf:
                        best_symbol = text
                        best_conf = conf

            if best_symbol and best_conf >= 0:
                hypotheses.append(
                    OcrHypothesis(symbol=best_symbol, confidence=best_conf, source=self.engine_name)
                )

        except Exception as e:
            logger.error(f"Ошибка TesseractEngine при чтении клетки: {e}")

        return hypotheses

    def recognize_line(
        self,
        processed_image: np.ndarray,
        allowed_chars: str = "",
        is_handwritten: bool = False,
    ) -> List[OcrHypothesis]:
        """Читает целую строку текста."""
        if not self.enabled:
            return []

        tess_img = self._prepare_image_for_tesseract(
            processed_image, pad_size=20, scale_to_height=128
        )

        if is_handwritten:
            lang = self._build_lang_string(need_cyrillic=True)
            # psm 6 — блок текста; лучше для многосимвольных рукописных строк
            config = f"--psm 6 --oem 1 -l {lang}"
        else:
            lang = self._build_lang_string(need_cyrillic=False)
            config = f"--psm 7 --oem 1 -l {lang}"
            if allowed_chars:
                config += f" -c tessedit_char_whitelist={allowed_chars}"

        try:
            data = pytesseract.image_to_data(
                tess_img, config=config, output_type=pytesseract.Output.DICT
            )
            line_text = ""
            confidences = []

            for i, text in enumerate(data["text"]):
                text = text.strip()
                if text:
                    line_text += text
                    conf = float(data["conf"][i]) / 100.0
                    if conf >= 0:
                        confidences.append(conf)

            if line_text:
                avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
                return [OcrHypothesis(symbol=line_text, confidence=avg_conf, source=f"{self.engine_name}_line")]

        except Exception as e:
            logger.error(f"Ошибка TesseractEngine при чтении строки: {e}")

        return []
