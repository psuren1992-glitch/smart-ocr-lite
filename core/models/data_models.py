from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

@dataclass
class OcrHypothesis:
    symbol: str
    confidence: float
    source: str  # e.g., "tesseract", "heuristic_dash", "easyocr"

@dataclass
class CellResult:
    task_number: int
    row_index: int
    cell_index: int
    bbox: Tuple[int, int, int, int]
    inner_bbox: Tuple[int, int, int, int]
    best_symbol: str = ""
    confidence: float = 0.0
    top_candidates: List[OcrHypothesis] = field(default_factory=list)
    is_doubtful: bool = False
    doubt_reason: str = ""
    is_empty: bool = True
    is_crossed_out: bool = False

@dataclass
class RowResult:
    task_number: int
    center_y: int
    locator_method: str
    bbox: Tuple[int, int, int, int]
    cells: List[CellResult] = field(default_factory=list)
    answer_text: str = ""
    confidence: float = 1.0
    filled_cells_count: int = 0
    recognized_cells_count: int = 0
    validation_notes: List[str] = field(default_factory=list)
