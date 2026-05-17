import cv2
import numpy as np

from core.thresholds import CellShapeThresholds, get_thresholds


class CellShapeRules:
    """
    Low-level image heuristics for cropped answer cells.

    This class intentionally contains only shape- and component-based rules so
    higher-level OCR orchestration can stay in SymbolClassifier.
    """

    def __init__(self, thresholds: CellShapeThresholds | None = None):
        self.t = thresholds or get_thresholds().cell_shape

    def is_crossed_out_pattern(self, binary: np.ndarray) -> bool:
        if binary is None or binary.size == 0:
            return False

        num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if num_labels <= 1:
            return False

        t = self.t
        h, w = binary.shape[:2]
        cell_area = float(max(1, h * w))
        foreground_ratio = float(cv2.countNonZero(binary)) / cell_area
        largest_area = 0
        significant_components = 0
        major_components = 0

        for label in range(1, num_labels):
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area < 8:
                continue
            significant_components += 1
            largest_area = max(largest_area, area)
            if area >= cell_area * t.min_component_area_ratio:
                major_components += 1

        if major_components >= t.min_major_components_cross and significant_components > t.min_significant_components_cross and foreground_ratio >= t.min_foreground_ratio_cross:
            return True

        if major_components >= 1 and largest_area > cell_area * t.alt_largest_area_ratio and significant_components > t.alt_significant_components_cross and foreground_ratio >= t.alt_foreground_ratio_cross:
            return True

        return False

    def remove_dotted_cell_frame(self, binary: np.ndarray) -> np.ndarray:
        """
        Remove the dotted answer-cell frame while keeping handwritten strokes.
        """
        if binary is None or binary.size == 0:
            return np.zeros((10, 10), dtype=np.uint8)

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if num_labels <= 1:
            return binary

        h, w = binary.shape[:2]
        areas = stats[1:, cv2.CC_STAT_AREA]
        largest_area = int(np.max(areas)) if len(areas) else 0
        cell_area = h * w

        if self.is_crossed_out_pattern(binary):
            return np.zeros_like(binary)

        if largest_area < max(self.t.min_largest_area_cell, cell_area * self.t.min_largest_area_cell_ratio):
            return np.zeros_like(binary)

        cleaned = np.zeros_like(binary)
        keep_large = max(120, largest_area * self.t.keep_area_factor)

        for label in range(1, num_labels):
            x, y, comp_w, comp_h, area = stats[label]
            cx, cy = centroids[label]

            if area >= keep_large:
                cleaned[labels == label] = 255
                continue

            in_middle = (0.18 * w < cx < 0.82 * w) and (0.18 * h < cy < 0.90 * h)
            looks_like_mark = area >= 25 and (comp_w >= 2 or comp_h >= 2)
            if in_middle and looks_like_mark:
                cleaned[labels == label] = 255

        return cleaned

    def remove_dotted_cell_frame_for_row(self, binary: np.ndarray) -> np.ndarray:
        """
        Row OCR must keep punctuation-only cells.
        """
        if binary is None or binary.size == 0:
            return np.zeros((10, 10), dtype=np.uint8)

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if num_labels <= 1:
            return binary

        h, w = binary.shape[:2]
        cleaned = np.zeros_like(binary)

        for label in range(1, num_labels):
            x, y, comp_w, comp_h, area = stats[label]
            cx, cy = centroids[label]

            near_border = (
                cx < 0.12 * w
                or cx > 0.88 * w
                or cy < 0.10 * h
                or cy > 0.94 * h
            )
            central = (0.14 * w < cx < 0.86 * w) and (0.12 * h < cy < 0.92 * h)
            punctuation_zone = (0.20 * w < cx < 0.80 * w) and (0.30 * h < cy < 0.94 * h)

            if area >= 85 and central:
                cleaned[labels == label] = 255
            elif area >= 10 and punctuation_zone and not near_border:
                cleaned[labels == label] = 255

        return cleaned

    def looks_like_minus(self, binary: np.ndarray) -> bool:
        if binary is None or binary.size == 0:
            return False

        total = float(max(1, binary.shape[0] * binary.shape[1]))
        ink_ratio = cv2.countNonZero(binary) / total
        if ink_ratio > 0.15:
            # Альтернативная ветка: жирная чёрточка, не двойка/единица
            if ink_ratio <= self.t.alt_ink_ratio_for_minus_ceiling:
                h, w = binary.shape[:2]
                num_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
                if num_labels >= 2:
                    for label in range(1, num_labels):
                        _x, _y, comp_w, comp_h, area = stats[label]
                        _cx, cy = centroids[label]
                        if area >= self.t.alt_min_height_px and comp_h >= self.t.alt_min_height_px and comp_h <= 0.55 * h:
                            if comp_w >= 2 * comp_h and 0.22 * h < cy < 0.70 * h:
                                return True
            return False

        num_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if num_labels <= 1:
            return False

        h, _w = binary.shape[:2]
        for label in range(1, num_labels):
            _x, _y, comp_w, comp_h, area = stats[label]
            _cx, cy = centroids[label]
            aspect = comp_w / float(max(1, comp_h))
            if area >= 20 and aspect >= 1.8 and comp_h <= 0.20 * h and 0.22 * h < cy < 0.70 * h:
                return True
        return False

    def looks_like_comma(self, binary: np.ndarray) -> bool:
        if binary is None or binary.size == 0:
            return False

        num_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if num_labels <= 1:
            return False

        h, w = binary.shape[:2]
        components = []
        for label in range(1, num_labels):
            x, y, comp_w, comp_h, area = stats[label]
            if area < 10:
                continue
            cx, cy = centroids[label]
            components.append(
                {
                    "x": x,
                    "y": y,
                    "w": comp_w,
                    "h": comp_h,
                    "area": area,
                    "cx": cx,
                    "cy": cy,
                }
            )

        if not components:
            return False

        components.sort(key=lambda item: item["area"], reverse=True)
        primary = components[0]
        cell_area = float(max(1, h * w))
        max_comma_area = max(220.0, cell_area * 0.08)

        if len(components) >= 2:
            secondary = components[1]
            return (
                primary["area"] <= max_comma_area
                and primary["w"] <= 0.38 * w
                and primary["h"] <= 0.55 * h
                and primary["cy"] > 0.50 * h
                and secondary["area"] <= primary["area"] * 0.25
                and secondary["cy"] < primary["cy"]
                and abs(secondary["cx"] - primary["cx"]) <= 0.35 * w
            )

        return (
            primary["area"] <= max_comma_area
            and primary["w"] <= 0.38 * w
            and primary["h"] <= 0.52 * h
            and 0.18 * w < primary["cx"] < 0.82 * w
            and primary["cy"] > 0.52 * h
        )

    def guess_digit_from_shape(self, processed_img: np.ndarray) -> str:
        if processed_img is None or processed_img.size == 0:
            return ""

        binary = (processed_img > 0).astype(np.uint8) * 255
        if cv2.countNonZero(binary) < 120:
            return ""

        points = cv2.findNonZero(binary)
        if points is None:
            return ""

        x, y, w, h = cv2.boundingRect(points)
        roi = binary[y:y + h, x:x + w]
        if roi.size == 0:
            return ""

        contours, hierarchy = cv2.findContours(roi, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        roi_area = float(max(1, roi.shape[0] * roi.shape[1]))
        holes = 0
        if hierarchy is not None:
            for index, item in enumerate(hierarchy[0]):
                if item[3] == -1:
                    continue
                hole_area = cv2.contourArea(contours[index])
                if (hole_area / roi_area) >= 0.02:
                    holes += 1

        top = roi[:max(1, h // 3), :]
        mid = roi[h // 3: 2 * h // 3, :]
        bot = roi[2 * h // 3:, :]
        left = roi[:, :max(1, w // 3)]
        center = roi[:, w // 3: 2 * w // 3]
        right = roi[:, 2 * w // 3:]

        def density(chunk: np.ndarray) -> float:
            return float(cv2.countNonZero(chunk)) / float(max(1, chunk.size))

        top_d = density(top)
        mid_d = density(mid)
        bot_d = density(bot)
        left_d = density(left)
        center_d = density(center)
        right_d = density(right)
        aspect = w / float(max(1, h))

        if holes >= 2:
            return "8"

        if holes == 1:
            if bot_d >= top_d + 0.08 and left_d >= right_d + 0.12 and mid_d <= 0.40:
                return "6"
            return "0"

        if left_d >= 0.50 and bot_d >= 0.52 and mid_d <= 0.36:
            return "6"

        if top_d >= 0.34 and mid_d >= 0.22 and bot_d <= 0.26 and center_d >= 0.38 and left_d <= 0.28:
            return "7"

        if aspect <= 0.5 and max(center_d, right_d) >= 0.55 and mid_d <= 0.52:
            return "1"

        if right_d >= 0.55 and center_d <= 0.22 and top_d >= 0.30 and mid_d >= 0.40:
            return "4"

        if top_d >= 0.35 and bot_d <= 0.22 and center_d >= 0.42 and left_d <= 0.25:
            return "7"

        if top_d >= 0.35 and mid_d >= 0.35 and bot_d >= 0.45 and left_d <= 0.25 and center_d >= 0.50 and right_d >= 0.40:
            return "3"

        if top_d >= 0.35 and mid_d >= 0.45 and 0.20 <= bot_d <= 0.35 and left_d >= 0.28 and center_d >= 0.40 and right_d >= 0.25:
            return "3"

        if top_d >= 0.22 and bot_d >= 0.25 and center_d >= 0.40 and left_d <= 0.25 and right_d <= 0.20:
            return "2"

        if top_d >= 0.40 and 0.24 <= mid_d <= 0.38 and 0.20 <= bot_d <= 0.36 and left_d >= 0.35 and center_d >= 0.40 and right_d <= 0.24:
            return "5"

        return ""

    def has_seven_mid_crossbar(self, binary: np.ndarray) -> bool:
        """
        Detect the school-style horizontal stroke across the middle leg of "7".

        This is intentionally different from generic minus/comma heuristics:
        the stroke must live inside the symbol bounding box and in the middle
        vertical band, so top serifs and bottom bases on "1" do not count.
        """
        if binary is None or binary.size == 0:
            return False

        binary = (binary > 0).astype(np.uint8) * 255
        if cv2.countNonZero(binary) < 20:
            return False

        points = cv2.findNonZero(binary)
        if points is None:
            return False

        x, y, w, h = cv2.boundingRect(points)
        if w < 4 or h < 8:
            return False

        roi = binary[y:y + h, x:x + w]
        y0 = max(0, int(h * self.t.seven_crossbar_y_low))
        y1 = min(h, int(h * self.t.seven_crossbar_y_high))
        if y1 <= y0:
            return False

        min_run = max(
            self.t.seven_crossbar_min_run_px,
            int(round(w * self.t.seven_crossbar_min_run_ratio)),
        )

        middle = roi[y0:y1, :]
        for row in middle:
            xs = np.flatnonzero(row > 0)
            if xs.size < min_run:
                continue

            longest = 1
            current = 1
            for idx in range(1, xs.size):
                if xs[idx] == xs[idx - 1] + 1:
                    current += 1
                    longest = max(longest, current)
                else:
                    current = 1
            if longest >= min_run:
                return True

        return False

    def looks_like_plain_one(self, binary: np.ndarray) -> bool:
        """
        A conservative "1" check for cases where another engine says "7".
        In this template family, a real 7 has a middle crossbar; without it,
        a narrow slanted/straight stroke is treated as a handwritten 1.
        """
        if binary is None or binary.size == 0:
            return False

        binary = (binary > 0).astype(np.uint8) * 255
        if cv2.countNonZero(binary) < 20:
            return False

        if self.has_seven_mid_crossbar(binary):
            return False

        points = cv2.findNonZero(binary)
        if points is None:
            return False

        _x, _y, w, h = cv2.boundingRect(points)
        if h < 8:
            return False

        aspect = w / float(max(1, h))
        return aspect <= self.t.one_plain_aspect_max

    def looks_like_mark(self, binary: np.ndarray) -> bool:
        """
        Детектирует наличие 'метки' (крестика или жирной точки) в ячейке.
        Используется для предметов типа География/Обществознание.
        """
        if binary is None or binary.size == 0:
            return False

        h, w = binary.shape[:2]
        total_pixels = h * w
        ink_pixels = cv2.countNonZero(binary)
        ink_ratio = ink_pixels / total_pixels

        # Метка не должна быть слишком пустой или слишком закрашенной
        if ink_ratio < 0.05 or ink_ratio > 0.60:
            return False

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if num_labels <= 1:
            return False

        # Ищем компоненту в центре ячейки
        for label in range(1, num_labels):
            area = stats[label, cv2.CC_STAT_AREA]
            if area < total_pixels * 0.04:
                continue

            cx, cy = centroids[label]
            # Проверяем, что центр компоненты находится в центральной области (с запасом)
            if 0.15 * w < cx < 0.85 * w and 0.15 * h < cy < 0.85 * h:
                # Дополнительная проверка на форму (не тонкая линия границы)
                comp_w = stats[label, cv2.CC_STAT_WIDTH]
                comp_h = stats[label, cv2.CC_STAT_HEIGHT]
                if comp_w > 0.15 * w and comp_h > 0.15 * h:
                    return True

        return False
