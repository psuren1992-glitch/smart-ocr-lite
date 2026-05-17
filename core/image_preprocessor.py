"""
Препроцессор изображений для улучшения качества OCR.
Решает ключевые проблемы:
  - Шум и артефакты сканирования
  - Перекос (deskew) страницы
  - Неравномерное освещение (тени, пятна)
  - Рукописный текст (адаптивная бинаризация вместо глобального OTSU)
"""
import cv2
import numpy as np
import logging
from typing import Tuple, Optional

from core.thresholds import PreprocessorThresholds, get_thresholds

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    def __init__(
        self,
        deskew: bool = True,
        denoise: bool = True,
        adaptive_thresh: bool = True,
        upscale_min_dpi: int = 200,  # Если изображение слишком мелкое — увеличим
        target_short_side: int = 2480,  # A4 при 300 DPI
        thresholds: PreprocessorThresholds | None = None,
    ):
        self.deskew = deskew
        self.denoise = denoise
        self.adaptive_thresh = adaptive_thresh
        self.upscale_min_dpi = upscale_min_dpi
        self.target_short_side = target_short_side
        self.t = thresholds or get_thresholds().preprocessor

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def prepare_for_pipeline(self, image: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Полный препроцессинг для пайплайна проверки бланков.
        Возвращает: (цветное BGR изображение, бинарное изображение для реперов)
        """
        # 1. Апскейл, если разрешение слишком низкое
        image = self._upscale_if_needed(image)

        # 2. Денойзинг (быстрый медианный фильтр)
        if self.denoise:
            image = self._denoise(image)

        # 3. Выравнивание яркости (CLAHE)
        image = self._normalize_illumination(image)

        # 4. Deskew (коррекция перекоса)
        if self.deskew:
            image = self._correct_skew(image)

        # 5. Бинаризация для детектора реперов (должна быть глобальной — реперы печатные)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binary_for_repers = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        return image, binary_for_repers

    def binarize_for_ocr(self, cell_gray: np.ndarray, is_handwritten: bool = True) -> np.ndarray:
        """
        Бинаризация вырезанной клетки под OCR.

        Для рукописных ответов используем адаптивную бинаризацию (Sauvola-подобную),
        которая устойчива к неравномерному фону и тонким чернилам.

        Возвращает изображение: чернила = 255, фон = 0 (инвертировано для контуров).
        """
        if cell_gray is None or cell_gray.size == 0:
            return np.zeros((10, 10), dtype=np.uint8)

        # Апскейл маленьких клеток — Tesseract хуже работает с мелкими символами
        h, w = cell_gray.shape[:2]
        if h < self.t.upscale_min_h or w < self.t.upscale_min_w:
            scale = max(self.t.upscale_min_h / h, self.t.upscale_min_w / w, self.t.upscale_min_scale)
            cell_gray = cv2.resize(cell_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        # Лёгкое размытие для устранения шума
        blurred = cv2.GaussianBlur(cell_gray, (3, 3), 0)

        if is_handwritten:
            # Адаптивная бинаризация — работает при неравномерном фоне
            # blockSize должен быть нечётным и >= 3; берем ~1/4 высоты клетки
            block_size = max(11, (cell_gray.shape[0] // 4) | 1)  # |1 — гарантируем нечётность
            binary = cv2.adaptiveThreshold(
                blurred, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                blockSize=block_size,
                C=8  # Константа: увеличьте если фон "грязный", уменьшите если текст теряется
            )
            # Морфология: убираем точечный шум и соединяем разорванные штрихи
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)   # убрать точки
            kernel2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel2)  # залить дырки в буквах
        else:
            # Глобальный OTSU для печатного текста
            _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        return binary

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _upscale_if_needed(self, image: np.ndarray) -> np.ndarray:
        """Масштабирует изображение если оно меньше целевого размера."""
        h, w = image.shape[:2]
        short_side = min(h, w)
        if short_side < self.target_short_side * 0.7:  # Меньше чем 70% от цели
            scale = self.target_short_side / short_side
            new_w, new_h = int(w * scale), int(h * scale)
            image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            logger.info(f"Изображение апскейлено: {w}x{h} → {new_w}x{new_h}")
        return image

    def _denoise(self, image: np.ndarray) -> np.ndarray:
        """Быстрый медианный фильтр для устранения шума сканирования."""
        # fastNlMeansDenoisingColored — качественнее, но медленный (h=3 — слабый денойзинг)
        # Медиана 3x3 — хороший баланс скорость/качество для бланков
        return cv2.medianBlur(image, 3)

    def _normalize_illumination(self, image: np.ndarray) -> np.ndarray:
        """
        Компенсация неравномерного освещения через CLAHE на L-канале LAB.
        Убирает тени от складок, пятна от сканера.
        """
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_channel, a, b = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l_eq = clahe.apply(l_channel)

        lab_eq = cv2.merge([l_eq, a, b])
        return cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)

    def _correct_skew(self, image: np.ndarray, max_angle_deg: float = 5.0) -> np.ndarray:
        """
        Коррекция перекоса страницы через метод проекций.
        Исправляет углы до ±5 градусов (типичный перекос при ручном сканировании).
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Грубая бинаризация для детекции строк текста
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Минимальная площадь текстовой области для анализа
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) < 100:
            return image  # Слишком мало пикселей, пропускаем

        # minAreaRect на всём тексте даёт угол перекоса
        rect = cv2.minAreaRect(coords)
        angle = rect[-1]

        # minAreaRect возвращает углы в диапазоне [-90, 0)
        # Приводим к диапазону (-45, 45]
        if angle < -45:
            angle = 90 + angle

        # Не трогаем, если угол незначительный или слишком большой (скорее всего ошибка)
        if abs(angle) < 0.3 or abs(angle) > max_angle_deg:
            return image

        logger.info(f"Коррекция перекоса: {angle:.2f}°")
        h, w = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            image, M, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE
        )
        return rotated
