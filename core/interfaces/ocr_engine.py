from abc import ABC, abstractmethod
import numpy as np
from typing import List
from core.models.data_models import OcrHypothesis

class BaseOcrEngine(ABC):
    """
    Абстрактный базовый класс для всех OCR-движков.
    Позволяет прозрачно заменять Tesseract на кастомные ONNX модели или EasyOCR.
    """
    
    def __init__(self, engine_name: str):
        self.engine_name = engine_name

    @abstractmethod
    def recognize_cell(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        """
        Распознает символ(ы) на бинаризованном/подготовленном изображении отдельной клетки.
        
        :param processed_image: Изображение клетки (NumPy array).
        :param allowed_chars: Whitelist допустимых символов.
        :return: Список гипотез, отсортированный по убыванию уверенности.
        """
        pass

    @abstractmethod
    def recognize_line(self, processed_image: np.ndarray, allowed_chars: str = "") -> List[OcrHypothesis]:
        """
        Резервный метод для распознавания целой строки (например, печатного номера задания).
        """
        pass