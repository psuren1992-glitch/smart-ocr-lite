"""Провайдер для shape-правил, используемых в CellClassifierFlow."""
import cv2
import numpy as np

from core.cell_shape_rules import CellShapeRules


class ShapeRulesProvider:
    """
    Инкапсулирует методы CellShapeRules, нужные CellClassifierFlow.
    Позволяет передавать их как единую зависимость вместо россыпи колбэков.
    """

    def __init__(self):
        self._rules = CellShapeRules()

    def looks_like_minus(self, binary: np.ndarray) -> bool:
        return self._rules.looks_like_minus(binary)

    def looks_like_comma(self, binary: np.ndarray) -> bool:
        return self._rules.looks_like_comma(binary)

    def looks_like_mark(self, binary: np.ndarray) -> bool:
        return self._rules.looks_like_mark(binary)

    def is_crossed_out_pattern(self, binary: np.ndarray) -> bool:
        return self._rules.is_crossed_out_pattern(binary)

    def remove_dotted_cell_frame(self, binary: np.ndarray) -> np.ndarray:
        return self._rules.remove_dotted_cell_frame(binary)

    def remove_dotted_cell_frame_for_row(self, binary: np.ndarray) -> np.ndarray:
        return self._rules.remove_dotted_cell_frame_for_row(binary)
