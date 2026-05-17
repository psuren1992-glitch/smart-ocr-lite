import cv2
import numpy as np
import logging
from dataclasses import dataclass, field
from typing import Dict, Tuple, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AlignmentMeta:
    success: bool = False
    repers_found: int = 0
    used_fallback: bool = False
    skew_angle: float = 0.0
    warnings: List[str] = field(default_factory=list)


class AlignmentService:
    def __init__(self, target_width: int, target_height: int, target_points: Dict[str, List[float]] = None):
        self.target_width = target_width
        self.target_height = target_height

        pad_x = 150
        pad_y = 150
        self.dst_pts = {
            "top_left":     [pad_x,                    pad_y],
            "top_right":    [self.target_width - pad_x, pad_y],
            "bottom_left":  [pad_x,                    self.target_height - pad_y],
            "bottom_right": [self.target_width - pad_x, self.target_height - pad_y],
        }
        if target_points:
            self.dst_pts.update({
                key: self._resolve_target_point(point)
                for key, point in target_points.items()
            })

    def _resolve_target_point(self, point: List[float]) -> List[int]:
        if max(point) <= 1.0001:
            return [int(round(point[0] * self.target_width)), int(round(point[1] * self.target_height))]
        return [int(round(point[0])), int(round(point[1]))]

    def align(
        self,
        image: np.ndarray,
        detected_repers: dict,
    ) -> Tuple[Optional[np.ndarray], AlignmentMeta]:
        """
        Выполняет перспективное преобразование на основе реперов.

        Fallback-стратегии при нехватке реперов:
          3 точки  → аффинное преобразование (сохраняет параллельность линий)
          2 точки  → масштабирование + сдвиг по доступным осям
          < 2 точек → возвращает исходное изображение с предупреждением
        """
        meta = AlignmentMeta(repers_found=len(detected_repers))
        keys = ["top_left", "top_right", "bottom_left", "bottom_right"]

        src_list, dst_list = [], []
        for key in keys:
            if key in detected_repers and detected_repers[key]:
                src_list.append(detected_repers[key])
                dst_list.append(self.dst_pts[key])

        n = len(src_list)

        if n == 4:
            # Идеальный случай: перспективное преобразование
            src_pts = np.array(src_list, dtype=np.float32)
            dst_pts = np.array(dst_list, dtype=np.float32)
            matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
            aligned = cv2.warpPerspective(
                image, matrix, (self.target_width, self.target_height)
            )
            meta.success = True

        elif n == 3:
            # Аффинное преобразование по 3 точкам
            meta.used_fallback = True
            meta.warnings.append(f"Найдено только {n} репера. Используется аффинное преобразование.")
            src_pts = np.array(src_list[:3], dtype=np.float32)
            dst_pts = np.array(dst_list[:3], dtype=np.float32)
            matrix = cv2.getAffineTransform(src_pts, dst_pts)
            aligned = cv2.warpAffine(
                image, matrix, (self.target_width, self.target_height)
            )
            meta.success = True

        elif n >= 2:
            # Только масштабирование и сдвиг (грубый fallback)
            meta.used_fallback = True
            meta.warnings.append(
                f"Найдено только {n} репера. Выравнивание ненадёжно — проверьте результат вручную."
            )
            # Простое масштабирование по bounding box двух точек
            sx = (dst_list[1][0] - dst_list[0][0]) / max(1, src_list[1][0] - src_list[0][0])
            sy = (dst_list[1][1] - dst_list[0][1]) / max(1, src_list[1][1] - src_list[0][1])
            sx = max(0.5, min(2.0, abs(sx))) if src_list[1][0] != src_list[0][0] else 1.0
            sy = max(0.5, min(2.0, abs(sy))) if src_list[1][1] != src_list[0][1] else 1.0

            tx = dst_list[0][0] - src_list[0][0] * sx
            ty = dst_list[0][1] - src_list[0][1] * sy
            matrix = np.array([[sx, 0, tx], [0, sy, ty]], dtype=np.float32)
            aligned = cv2.warpAffine(image, matrix, (self.target_width, self.target_height))
            meta.success = True

        else:
            # Реперов нет: возвращаем масштабированное изображение без коррекции
            meta.used_fallback = True
            meta.warnings.append(
                "Реперы не найдены! Изображение масштабировано без коррекции перспективы. "
                "Результат может быть неточным."
            )
            h, w = image.shape[:2]
            aligned = cv2.resize(image, (self.target_width, self.target_height), interpolation=cv2.INTER_CUBIC)
            meta.success = True  # Возвращаем что есть, пусть дальше пробует

        return aligned, meta
