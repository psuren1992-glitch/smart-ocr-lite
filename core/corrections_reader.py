import numpy as np
import logging
from typing import List, Dict, Any, Tuple
from core.models.data_models import RowResult, CellResult
from core.row_locator import RowLocator
from core.cell_extractor import CellExtractor
from core.symbol_classifier import SymbolClassifier

logger = logging.getLogger(__name__)

class CorrectionRow:
    """Внутренняя DTO для хранения данных одной строки замены"""
    def __init__(self, row_center_y: int):
        self.row_center_y = row_center_y
        self.task_cells: List[CellResult] = []
        self.answer_cells: List[CellResult] = []
        self.task_number: int = -1
        self.task_confidence: float = 0.0
        self.is_valid: bool = False  # Флаг надежности номера задания
        self.warnings: List[str] = []

class CorrectionsReader:
    def __init__(self, row_locator: RowLocator, cell_extractor: CellExtractor, classifier: SymbolClassifier):
        self.row_locator = row_locator
        self.cell_extractor = cell_extractor
        self.classifier = classifier
        
        # Минимальная уверенность для применения замены (ТЗ 14.3)
        self.min_task_confidence = 0.80 

    def read_block(self, aligned_image: np.ndarray, config: Dict[str, Any], block_side: str) -> List[CorrectionRow]:
        """
        Читает блок замен (left или right).
        config - это словарь "corrections" -> "left" из шаблона.
        """
        results = []
        
        # 1. Ищем геометрические центры строк внутри row_band
        # Создаем фиктивный конфиг для переиспользования RowLocator
        band_config = {
            "label_zone": config["row_band"],
            "answer_zone": config["row_band"],
            "tasks": [0] * 6 # Предполагаем максимум 6 полей для замен (уйдет в конфиг шаблона)
        }
        
        # locator найдет реальные пики строк (печатные элементы)
        found_rows = self.row_locator.locate_rows(aligned_image, band_config)
        
        row_height_half = 30 # Магическое число, должно приходить из шаблона
        
        for row_idx, base_row in enumerate(found_rows):
            corr_row = CorrectionRow(row_center_y=base_row.center_y)
            cy = base_row.center_y
            
            # 2. Формируем BBox для номера задания и ответа
            tz = config["task_zone"]
            az = config["answer_zone"]
            
            task_bbox = (tz[0], cy - row_height_half, tz[2], cy + row_height_half)
            answer_bbox = (az[0], cy - row_height_half, az[2], cy + row_height_half)
            
            # Обертка в RowResult для совместимости с CellExtractor
            temp_task_row = RowResult(task_number=-1, center_y=cy, locator_method="corrections", bbox=task_bbox)
            temp_answer_row = RowResult(task_number=-1, center_y=cy, locator_method="corrections", bbox=answer_bbox)
            
            # 3. Нарезаем на клетки (например, 2 клетки под номер задания, 17 под ответ)
            # В реальной системе эти числа берутся из шаблона (cell_count_task, cell_count_answer)
            self.cell_extractor.extract_cells(aligned_image, temp_task_row, cells_count=2)
            self.cell_extractor.extract_cells(aligned_image, temp_answer_row, cells_count=17)
            
            corr_row.task_cells = temp_task_row.cells
            corr_row.answer_cells = temp_answer_row.cells
            
            # 4. Распознаем клетки
            for cell in corr_row.task_cells + corr_row.answer_cells:
                self.classifier.classify(aligned_image, cell)
                
            # 5. Парсим номер задания
            task_str = "".join([c.best_symbol for c in corr_row.task_cells if c.best_symbol]).strip()
            
            if not task_str:
                # Пустая строка замены, пропускаем
                continue
                
            try:
                corr_row.task_number = int(task_str)
                # Уверенность номера задания — это средняя уверенность его цифр
                confidences = [c.confidence for c in corr_row.task_cells if not c.is_empty]
                corr_row.task_confidence = sum(confidences) / len(confidences) if confidences else 0.0
                
                if corr_row.task_confidence >= self.min_task_confidence:
                    corr_row.is_valid = True
                else:
                    corr_row.warnings.append(f"Низкая уверенность распознавания номера задания: {corr_row.task_confidence:.2f}")
                    
            except ValueError:
                corr_row.warnings.append(f"Не удалось спарсить номер задания: '{task_str}'")

            results.append(corr_row)
            
        return results