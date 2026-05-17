import cv2
import numpy as np
from typing import Dict, Tuple, Optional, List
import logging

logger = logging.getLogger(__name__)

class ReperDetector:
    def __init__(self, expected_zones: Dict[str, List[float]], page_size: Tuple[int, int]):
        """
        :param expected_zones: Словарь зон из JSON шаблона, например:
                               {"top_left": [0.0, 0.0, 0.2, 0.2], ...}
        :param page_size: (width, height) выровненной страницы из шаблона.
        """
        self.expected_zones = expected_zones
        self.page_size = page_size
        
        # Параметры фильтрации (в идеале выносятся в app_config.json)
        self.min_area = 100
        self.max_area = 50000
        self.max_aspect_ratio = 1.5

    def _get_zone_pixel_coords(self, img_shape: Tuple[int, int], zone_rel: List[float]) -> Tuple[int, int, int, int]:
        h, w = img_shape[:2]
        x1 = int(zone_rel[0] * w)
        y1 = int(zone_rel[1] * h)
        x2 = int(zone_rel[2] * w)
        y2 = int(zone_rel[3] * h)
        return x1, y1, x2, y2

    def detect(self, binary_image: np.ndarray) -> Dict[str, Tuple[int, int]]:
        """
        Ищет реперные точки в бинаризованном изображении (черные метки на белом фоне).
        Возвращает словарь {имя_зоны: (cx, cy)}.
        """
        detected_repers = {}
        
        # Инвертируем для findContours (ищем белые объекты на черном фоне)
        inv_img = cv2.bitwise_not(binary_image)
        
        contours, _ = cv2.findContours(inv_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Предварительно фильтруем контуры по площади и форме
        valid_contours = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if self.min_area < area < self.max_area:
                x, y, w, h = cv2.boundingRect(cnt)
                aspect_ratio = max(w/h, h/w)
                extent = area / max(1, w * h)
                # Реперы - плотные объекты, почти квадраты/круги, допускаем искажения
                if aspect_ratio <= self.max_aspect_ratio and extent >= 0.45:
                    cx = x + w // 2
                    cy = y + h // 2
                    valid_contours.append((cx, cy, area, extent, cnt))

        # Распределяем по зонам
        for zone_name, zone_rel in self.expected_zones.items():
            x1, y1, x2, y2 = self._get_zone_pixel_coords(binary_image.shape, zone_rel)
            
            candidates = []
            for cx, cy, area, extent, cnt in valid_contours:
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    candidates.append((cx, cy, area, extent))
            
            if candidates:
                # Берем самую крупную/плотную метку в зоне
                best_candidate = max(candidates, key=lambda c: (c[2], c[3]))
                detected_repers[zone_name] = (best_candidate[0], best_candidate[1])
                logger.debug(f"Найден репер {zone_name} на ({best_candidate[0]}, {best_candidate[1]})")
            else:
                logger.warning(f"Репер {zone_name} не найден в ожидаемой зоне.")

        return detected_repers
