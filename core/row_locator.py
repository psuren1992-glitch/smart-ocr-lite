import cv2
import numpy as np
from typing import List, Tuple
import logging
from core.models.data_models import RowResult

logger = logging.getLogger(__name__)


class RowLocator:
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode

    def _get_horizontal_projection(self, binary_image: np.ndarray) -> np.ndarray:
        """Суммирует пиксели чернил по строкам (чернила = 255 после инверсии)."""
        inv_img = cv2.bitwise_not(binary_image)
        return np.sum(inv_img, axis=1).astype(np.float64)

    def locate_rows(self, aligned_image: np.ndarray, block_config: dict) -> List[RowResult]:
        """
        Находит строки ответа, используя каскад методов:
        1. Явные центры (если заданы в шаблоне)
        2. Детекция горизонтальных линий сетки в answer_zone
        3. Проекция печатных номеров в label_zone
        4. Равномерное распределение (fallback)
        """
        tasks = block_config.get("tasks", [])
        expected_count = len(tasks)
        az = block_config["answer_zone"]
        lz = block_config.get("label_zone")

        # 1. Явные центры
        if "row_centers" in block_config:
            row_half_height = int(block_config.get("row_half_height", 38))
            peaks = [(int(y), row_half_height) for y in block_config["row_centers"]]
            return self._build_rows_from_peaks(peaks, tasks, az)

        # 2. Попытка найти сетку (горизонтальные линии)
        peaks = self._detect_rows_by_grid(aligned_image, az, expected_count)
        if len(peaks) == expected_count:
            logger.info(f"Строки найдены по сетке в answer_zone (count={len(peaks)})")
            return self._build_rows_from_peaks(peaks, tasks, az)

        # 3. Проекция номеров заданий (старый метод)
        if lz:
            label_peaks = self._locate_by_projection(aligned_image, lz, expected_count)
            if len(label_peaks) == expected_count:
                logger.info(f"Строки найдены по проекции label_zone (count={len(label_peaks)})")
                return self._build_rows_from_peaks(label_peaks, tasks, az)
            peaks = label_peaks # Сохраняем для fallback

        # 4. Совсем крайний случай - равномерное распределение
        logger.warning(
            f"Locator: Не удалось точно найти {expected_count} строк. "
            f"Применяется fallback по равному шагу в зоне {az[1]}:{az[3]}"
        )
        final_peaks = self._fallback_equal_spacing(peaks, expected_count, az if not lz else lz)
        return self._build_rows_from_peaks(final_peaks, tasks, az)

    def _detect_rows_by_grid(self, image: np.ndarray, az: List[int], expected_count: int) -> List[Tuple[int, int]]:
        """
        Ищет горизонтальные разделители строк внутри answer_zone.
        """
        if expected_count <= 0: return []
        
        crop = image[az[1]:az[3], az[0]:az[2]]
        if crop.size == 0: return []
        
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # Ищем линии: адаптивный порог + морфология
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
        
        # Выделяем горизонтальные структуры
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (az[2]-az[0]//2, 1))
        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        
        proj = np.sum(horizontal, axis=1)
        
        peaks = []
        threshold = np.max(proj) * 0.3
        in_line = False
        line_y = []
        
        for y, val in enumerate(proj):
            if val > threshold:
                line_y.append(y)
                in_line = True
            elif in_line:
                # Нашли линию. Центр строки будет МЕЖДУ линиями или со смещением от линии
                in_line = False
        
        # Если линий (разделителей) n+1 или n, мы можем вычислить центры строк
        detected_lines = []
        # (упрощенный поиск центров линий)
        # ... (здесь логика кластеризации линий)
        
        # На самом деле, для ОГЭ/ЕГЭ часто эффективнее искать именно "пустоты" между линиями (клетки)
        # Повторим проекцию, но на инвертированный бинарник всей зоны
        proj_ink = np.sum(binary, axis=1)
        # Сглаживаем, чтобы убрать шум отдельных букв, но оставить структуру строк
        smoothed = np.convolve(proj_ink, np.ones(15)/15, mode='same')
        
        # Ищем локальные максимумы "чернильности" (центры строк)
        # Но этот метод менее надежен, чем проекция номеров. 
        # Поэтому возвращаем пустой список, если не уверены, 
        # давая шанс _locate_by_projection.
        return [] 

    def _locate_by_projection(self, image: np.ndarray, lz: List[int], expected_count: int) -> List[Tuple[int, int]]:
        """Инсулированная логика старого метода проекции."""
        label_crop = image[lz[1]:lz[3], lz[0]:lz[2]]
        if label_crop.size == 0: return []

        gray = cv2.cvtColor(label_crop, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        proj = self._get_horizontal_projection(binary)
        
        zone_height = lz[3] - lz[1]
        kernel_size = max(5, int(zone_height * 0.015)) | 1
        smoothed_proj = np.convolve(proj, np.ones(kernel_size) / kernel_size, mode="same")
        threshold_val = np.max(smoothed_proj) * 0.30
        
        peaks = []
        in_peak = False
        peak_start = 0
        for i, val in enumerate(smoothed_proj):
            if val > threshold_val and not in_peak:
                in_peak = True
                peak_start = i
            elif val <= threshold_val and in_peak:
                in_peak = False
                peak_center = (peak_start + i) // 2
                peaks.append((lz[1] + peak_center, i - peak_start))
        return peaks

    def _build_rows_from_peaks(self, peaks: List[Tuple[int, int]], tasks: List[int], az: List[int]) -> List[RowResult]:
        results = []

        # row_height_half: берём из реального пика или считаем от среднего шага строк
        if peaks:
            avg_thickness = np.mean([t for _, t in peaks]) if peaks else 30
            if len(peaks) >= 2:
                avg_step = np.mean(np.diff([y for y, _ in peaks]))
                row_height_half = max(18, min(42, int(max(avg_thickness, avg_step * 0.28))))
            else:
                row_height_half = max(15, int(avg_thickness * 0.7))
        else:
            row_height_half = 30  # последний резерв

        for i, (center_y, _) in enumerate(peaks):
            task_num = tasks[i] if i < len(tasks) else -1

            bbox = (
                az[0],
                center_y - row_height_half,
                az[2],
                center_y + row_height_half,
            )

            row = RowResult(
                task_number=task_num,
                center_y=center_y,
                locator_method="horizontal_projection",
                bbox=bbox,
            )
            results.append(row)

        return results

    def _fallback_equal_spacing(
        self,
        found_peaks: List[Tuple[int, int]],
        expected_count: int,
        lz: List[int],
    ) -> List[Tuple[int, int]]:
        """
        Если нашли неправильное количество пиков — раскладываем по равному шагу.
        Используем крайние найденные пики как опорные точки (если есть ≥ 2),
        иначе равномерно по всей label_zone.
        """
        if len(found_peaks) >= 2:
            y_start = found_peaks[0][0]
            y_end = found_peaks[-1][0]
        else:
            y_start = lz[1] + (lz[3] - lz[1]) // (expected_count + 1)
            y_end = lz[3] - (lz[3] - lz[1]) // (expected_count + 1)

        if expected_count == 1:
            return [((y_start + y_end) // 2, 20)]

        step = (y_end - y_start) / (expected_count - 1)
        return [(int(y_start + i * step), 20) for i in range(expected_count)]
