import os
import cv2
import json
import logging
import numpy as np
from typing import List, Dict, Any
from core.models.data_models import RowResult
from core.corrections_reader import CorrectionRow
from core.cell_grid import draw_template_cells_overlay

logger = logging.getLogger(__name__)

class DebugExporter:
    def __init__(self, base_dir: str = "debug_crops"):
        self.base_dir = base_dir

    def export_failure(self, work_id: str, result_json: Dict[str, Any], image: np.ndarray = None, image_name: str = "input.png"):
        work_dir = os.path.join(self.base_dir, work_id)
        os.makedirs(work_dir, exist_ok=True)

        if image is not None:
            cv2.imwrite(os.path.join(work_dir, image_name), image)

        with open(os.path.join(work_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(result_json, f, ensure_ascii=False, indent=4)

        logger.info(f"Отладочные материалы (Debug) сохранены в: {work_dir}")

    def export(self, work_id: str, aligned_img: np.ndarray, main_rows: List[RowResult], corrections: List[CorrectionRow], result_json: Dict[str, Any], template: Dict[str, Any] = None):
        """
        Сохраняет отладочные изображения: выровненный скан, наложение строк и клеток.
        """
        if aligned_img is None:
            return

        # Создаем папку для конкретной работы
        work_dir = os.path.join(self.base_dir, work_id)
        os.makedirs(work_dir, exist_ok=True)

        # 1. Сохраняем чистый выровненный скан
        cv2.imwrite(os.path.join(work_dir, "aligned.png"), aligned_img)

        # 2. Рисуем сетку (overlay) поверх скана, чтобы видеть, как алгоритм нарезал клетки
        overlay = aligned_img.copy()
        
        # Отрисовка основных строк
        for row in main_rows:
            rx1, ry1, rx2, ry2 = row.bbox
            # Зеленая рамка для строки
            cv2.rectangle(overlay, (rx1, ry1), (rx2, ry2), (0, 200, 0), 2)
            
            # Синие рамки для каждой клетки внутри строки
            for cell in row.cells:
                cx1, cy1, cx2, cy2 = cell.inner_bbox
                cv2.rectangle(overlay, (cx1, cy1), (cx2, cy2), (255, 0, 0), 1)

        # Сохраняем картинку с нарисованной сеткой
        cv2.imwrite(os.path.join(work_dir, "row_overlay.png"), overlay)

        if template:
            template_overlay = draw_template_cells_overlay(aligned_img, template)
            cv2.imwrite(os.path.join(work_dir, "template_cells_overlay.png"), template_overlay)

        # 3. Сохраняем JSON с результатами в ту же папку для истории
        with open(os.path.join(work_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(result_json, f, ensure_ascii=False, indent=4)

        logger.info(f"Отладочные материалы (Debug) сохранены в: {work_dir}")
