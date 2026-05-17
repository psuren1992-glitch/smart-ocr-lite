import cv2
import numpy as np
from typing import List
import logging
from core.models.data_models import RowResult, CellResult

logger = logging.getLogger(__name__)

class CellExtractor:
    def __init__(
        self,
        padding_ratio: float = 0.15,
        padding_x_ratio: float | None = None,
        padding_y_ratio: float | None = None,
    ):
        """
        :param padding_ratio: Доля ширины/высоты клетки, которая отсекается как рамка.
                              Например, 0.15 означает срез 15% с каждой стороны.
        """
        self.padding_x_ratio = padding_ratio if padding_x_ratio is None else padding_x_ratio
        self.padding_y_ratio = padding_ratio if padding_y_ratio is None else padding_y_ratio

    def extract_cells(self, aligned_image: np.ndarray, row: RowResult, cells_count: int) -> None:
        """
        Разбивает найденную строку на клетки и заполняет список row.cells.
        Мутирует переданный объект RowResult.
        """
        x1, y1, x2, y2 = row.bbox
        row_width = x2 - x1
        
        # Защита от нулевой ширины
        if row_width <= 0 or cells_count <= 0:
            logger.error(f"Некорректные параметры для извлечения клеток: width={row_width}, count={cells_count}")
            return

        cell_width = row_width / cells_count
        row_height = y2 - y1
        
        pad_x = int(cell_width * self.padding_x_ratio)
        pad_y = int(row_height * self.padding_y_ratio)

        for i in range(cells_count):
            cell_x1 = int(x1 + i * cell_width)
            cell_x2 = int(x1 + (i + 1) * cell_width)
            
            # Внутренний bbox (без рамок)
            inner_x1 = cell_x1 + pad_x
            inner_y1 = y1 + pad_y
            inner_x2 = cell_x2 - pad_x
            inner_y2 = y2 - pad_y
            
            # Защита от инверсии координат из-за слишком большого padding
            inner_x2 = max(inner_x1 + 1, inner_x2)
            inner_y2 = max(inner_y1 + 1, inner_y2)

            cell_result = CellResult(
                task_number=row.task_number,
                row_index=row.task_number, # В контексте ОГЭ/ЕГЭ номер строки часто совпадает с номером задания
                cell_index=i,
                bbox=(cell_x1, y1, cell_x2, y2),
                inner_bbox=(inner_x1, inner_y1, inner_x2, inner_y2)
            )
            row.cells.append(cell_result)
            
        logger.debug(f"Task {row.task_number}: извлечено {cells_count} клеток.")
