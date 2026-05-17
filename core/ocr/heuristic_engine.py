import cv2
import numpy as np
from typing import List, Tuple
import logging
from core.interfaces.ocr_engine import BaseOcrEngine
from core.models.data_models import OcrHypothesis

logger = logging.getLogger(__name__)

class HeuristicEngine(BaseOcrEngine):
    def __init__(self, empty_threshold: float = 0.02):
        super().__init__(engine_name="heuristic")
        # Порог заполненности клетки чернилами (2% черных пикселей)
        self.empty_threshold = empty_threshold

    def _get_ink_density(self, binary_cell: np.ndarray) -> float:
        """Считает процент черных пикселей (предполагаем, что чернила = 255)."""
        total_pixels = binary_cell.shape[0] * binary_cell.shape[1]
        if total_pixels == 0:
            return 0.0
        ink_pixels = cv2.countNonZero(binary_cell)
        return ink_pixels / total_pixels

    def recognize_cell(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        """
        processed_image: Инвертированное бинарное изображение внутреннего bbox клетки (чернила = 255).
        """
        hypotheses = []
        density = self._get_ink_density(processed_image)

        # 1. Проверка на пустую клетку
        if density < self.empty_threshold:
            hypotheses.append(OcrHypothesis(symbol="", confidence=0.99, source=self.engine_name))
            return hypotheses

        # Находим компоненты связности
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(processed_image, connectivity=8)
        
        # Если нет объектов (кроме фона)
        if num_labels <= 1:
            hypotheses.append(OcrHypothesis(symbol="", confidence=0.99, source=self.engine_name))
            return hypotheses

        component_areas = stats[1:, cv2.CC_STAT_AREA]
        largest_area = int(np.max(component_areas)) if len(component_areas) else 0
        component_count = num_labels - 1
        cell_area = processed_image.shape[0] * processed_image.shape[1]

        # Пустые клетки на бланке не совсем пустые: внутри остаются точки пунктирной рамки.
        # У них много мелких компонентов и нет крупного связного штриха рукописного символа.
        if component_count >= 3 and largest_area < max(220, cell_area * 0.035):
            hypotheses.append(OcrHypothesis(symbol="", confidence=0.98, source=self.engine_name))
            return hypotheses

        # Ищем главный объект (исключая фон - label 0)
        largest_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        x, y, w, h, area = stats[largest_label]
        
        cell_h, cell_w = processed_image.shape
        aspect_ratio = w / float(h) if h > 0 else 0
        
        # 2. Эвристика: Минус "-"
        # Широкий, невысокий, находится примерно по центру или чуть выше
        if aspect_ratio > 2.0 and area > (cell_w * cell_h * 0.05):
            center_y = y + h/2
            if 0.3 * cell_h < center_y < 0.7 * cell_h:
                hypotheses.append(OcrHypothesis(symbol="-", confidence=0.85, source=self.engine_name))

        # 4. Эвристика: Семерка "7" с перекладиной
        # Важное правило: если в центре клетки есть четкая горизонтальная линия (перекладина), 
        # то это Семерка. Без перекладины это может быть Единица (1) или Семерка (7) без черты.
        else:
            # Ищем перекладину: горизонтальная линия в средней трети высоты
            mid_y1 = int(cell_h * 0.35)
            mid_y2 = int(cell_h * 0.65)
            mid_zone = processed_image[mid_y1:mid_y2, :]
            
            # Считаем проекцию на ось X (суммируем пиксели в каждой колонке)
            # Если есть длинная горизонтальная линия, то сумма будет стабильно высокой в ряде колонок
            # Но проще искать по рядам: суммируем пиксели в каждом ряду
            row_sums = np.sum(mid_zone, axis=1) / 255
            # Если есть ряд, где заполнено > 50% ширины - это перекладина
            has_bar = any(row_sum > (cell_w * 0.45) for row_sum in row_sums)
            
            if has_bar:
                # Если есть черта, то это почти наверняка 7
                hypotheses.append(OcrHypothesis(symbol="7", confidence=0.92, source=f"{self.engine_name}_bar"))
            
        # 3. Эвристика: Запятая ","
        # Маленькая, вытянута по вертикали или диагонали, расположена внизу
        if (
            area < (cell_w * cell_h * 0.045)
            and w < (cell_w * 0.45)
            and h < (cell_h * 0.55)
            and (y + h) > (0.50 * cell_h)
        ):
             hypotheses.append(OcrHypothesis(symbol=",", confidence=0.72, source=self.engine_name))

        return hypotheses

    def recognize_line(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        # Эвристики обычно работают только на уровне изолированных символов
        return []
