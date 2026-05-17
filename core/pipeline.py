import os
import csv
import cv2
import json
import numpy as np
from datetime import datetime
from typing import Dict, Any

from core.reper_detector import ReperDetector
from core.alignment import AlignmentService
from core.row_locator import RowLocator
from core.cell_extractor import CellExtractor
from core.symbol_classifier import SymbolClassifier
from core.corrections_reader import CorrectionsReader
from core.answer_resolver import AnswerResolver
from core.scoring import ScoringService
from core.debug_tools import DebugExporter
from core.image_preprocessor import ImagePreprocessor
from core.cell_grid import expand_grid


class DocumentProcessorPipeline:
    def __init__(
        self,
        template: Dict[str, Any],
        answer_key: Dict[str, str],
        classifier: SymbolClassifier,
        handwritten_mode: bool = False,
        debug_dir: str = "debug_crops",
        ocr_truth_mode: bool = False,
    ):
        self.template = template
        self.page_size = tuple(template.get("page_size", [2480, 3508]))
        self.handwritten_mode = handwritten_mode
        self.ocr_truth_mode = ocr_truth_mode

        self.preprocessor = ImagePreprocessor(
            deskew=True,
            denoise=True,
            adaptive_thresh=True,
        )
        self.reper_detector = ReperDetector(template["repers"]["expected_zones"], self.page_size)
        self.alignment = AlignmentService(
            self.page_size[0],
            self.page_size[1],
            template["repers"].get("target_points"),
        )
        self.row_locator = RowLocator()
        self.cell_extractor = CellExtractor(
            padding_x_ratio=0.04,
            padding_y_ratio=0.01,
        )
        self.classifier = classifier

        self.corrections_reader = CorrectionsReader(self.row_locator, self.cell_extractor, self.classifier)
        self.resolver = AnswerResolver(
            classifier=self.classifier,
            answer_key=answer_key,
            enable_math_answer_healing=bool(template.get("enable_math_answer_healing", True)),
            enable_answer_key_guidance=bool(template.get("enable_answer_key_guidance", True)) and not ocr_truth_mode,
        )
        self.scoring = ScoringService(answer_key)
        self.debug_exporter = DebugExporter(debug_dir)

    def export_cells_for_labeling(
        self,
        aligned_img,
        all_rows,
        work_id: str,
        out_dir: str = "data/labeling",
    ) -> str | None:
        if not os.path.isabs(out_dir):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            out_dir = os.path.join(base_dir, out_dir)
        out_dir = os.path.normpath(out_dir)

        os.makedirs(out_dir, exist_ok=True)
        img_dir = os.path.normpath(os.path.join(out_dir, work_id))
        os.makedirs(img_dir, exist_ok=True)

        csv_path = os.path.normpath(os.path.join(out_dir, f"{work_id}.csv"))
        rows_out = []

        for row in all_rows:
            task = row.task_number
            for cell in row.cells:
                if cell.is_empty:
                    continue

                x1, y1, x2, y2 = cell.bbox
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(aligned_img.shape[1], x2), min(aligned_img.shape[0], y2)
                if x2 <= x1 or y2 <= y1:
                    continue

                crop = aligned_img[y1:y2, x1:x2]
                fname = f"task{task}_cell{cell.cell_index}.png"
                fpath = os.path.normpath(os.path.join(img_dir, fname))
                cv2.imwrite(fpath, crop)
                rows_out.append(
                    {
                        "task": task,
                        "cell_index": cell.cell_index,
                        "predicted": cell.best_symbol,
                        "confidence": round(cell.confidence, 3),
                        "correct": "",
                        "image_path": fpath,
                    }
                )

        if not rows_out:
            return None

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
            writer.writeheader()
            writer.writerows(rows_out)

        return os.path.normpath(os.path.abspath(csv_path))

    def get_doubt_summary(self, rows) -> Dict[str, Any]:
        total_cells = sum(len(row.cells) for row in rows)
        all_doubtful = [cell for row in rows for cell in row.cells if cell.is_doubtful]
        empty_no_hypothesis = [
            cell for cell in all_doubtful if cell.doubt_reason == "No hypotheses generated"
        ]
        low_confidence = [
            cell for cell in all_doubtful if cell.doubt_reason.startswith("Low confidence")
        ]
        close_candidates = [
            cell for cell in all_doubtful if cell.doubt_reason.startswith("Close candidates")
        ]
        crossed_out_cells = [cell for row in rows for cell in row.cells if getattr(cell, "is_crossed_out", False)]
        return {
            "total_cells": total_cells,
            "empty_no_hypothesis": len(empty_no_hypothesis),
            "low_confidence": len(low_confidence),
            "close_candidates": len(close_candidates),
            "crossed_out": len(crossed_out_cells),
            "real_doubtful": len(low_confidence) + len(close_candidates),
            "details": [
                {
                    "cell": cell.cell_index,
                    "symbol": cell.best_symbol,
                    "confidence": round(cell.confidence, 3),
                    "reason": cell.doubt_reason,
                }
                for cell in low_confidence + close_candidates
            ],
        }

    def process(self, image_path: str, work_id: str, save_debug: bool = True) -> Dict[str, Any]:
        """Запускает полный пайплайн проверки одного изображения."""

        # 1. Загрузка
        image = cv2.imread(image_path)
        if image is None:
            result_json = {"work_id": work_id, "status": "failed", "error": f"Не удалось загрузить: {image_path}"}
            if save_debug:
                self.debug_exporter.export_failure(work_id, result_json)
            return result_json

        # 2. Препроцессинг: денойзинг, deskew, нормализация освещения
        #    Возвращает улучшенное цветное изображение и бинарное (для реперов)
        image, binary_for_repers = self.preprocessor.prepare_for_pipeline(image)

        # 3. Геометрия: поиск реперов и выравнивание перспективы
        repers = self.reper_detector.detect(binary_for_repers)
        aligned_img, align_meta = self.alignment.align(image, repers)

        if aligned_img is None:
            result_json = {"work_id": work_id, "status": "failed", "alignment_meta": align_meta.__dict__}
            if save_debug:
                self.debug_exporter.export_failure(work_id, result_json, image=image, image_name="preprocessed.png")
            return result_json

        # 4. Поиск строк и нарезка клеток (основной блок ответов)
        all_main_rows = []
        for side in ["left", "right"]:
            block_config = self.template["answer_blocks"][side]
            rows = self.row_locator.locate_rows(aligned_img, block_config)

            for row in rows:
                self.cell_extractor.extract_cells(aligned_img, row, cells_count=block_config["cell_count"])
                
                field_type = block_config.get("type", "math")
                allowed_chars = block_config.get("allowed_chars", "0123456789-,.")

                if field_type == "text":
                    # Для текстовых ответов (Русский язык, Литература) используем распознавание строкой
                    # Это позволяет PaddleOCR и Google Vision видеть контекст всего слова
                    row.answer_text = self.classifier.recognize_line(
                        aligned_img,
                        row.bbox,
                        allowed_chars=allowed_chars,
                        is_handwritten=True
                    )
                else:
                    # Для математики оставляем проверенный поклеточный метод с голосованием
                    row.answer_text = self.classifier.classify_row(
                        aligned_img,
                        row.cells,
                        allowed_chars=allowed_chars,
                        row=row,
                    )
                    
                for cell in row.cells:
                    self.classifier.classify(aligned_img, cell, allowed_chars=allowed_chars)
            all_main_rows.extend(rows)

        # 5. Блок замен (исправлений)
        all_corrections = []
        if self.template.get("enable_corrections", False) and "corrections" in self.template:
            for side in ["left", "right"]:
                corr_config = self.template["corrections"][side]
                corrs = self.corrections_reader.read_block(aligned_img, corr_config, side)
                all_corrections.extend(corrs)

        # 5b. Распознавание ФИО
        participant_info = self._process_participant_info(aligned_img)

        # 6. Сборка ответов и оценка
        doubt_summary = self.get_doubt_summary(all_main_rows)
        resolved_data = self.resolver.resolve(all_main_rows, all_corrections, aligned_image=aligned_img)
        score_data = self.scoring.score(resolved_data["answers_final"])

        # 7. Итоговый JSON
        result_json = {
            "work_id": work_id,
            "timestamp": datetime.now().isoformat(),
            "template_id": self.template.get("template_id"),
            "source_file": os.path.basename(image_path),
            "handwritten_mode": self.handwritten_mode,
            "ocr_truth_mode": self.ocr_truth_mode,
            "alignment_meta": align_meta.__dict__,
            "participant_info": participant_info,
            "template_cell_grids": {
                name: {
                    "count": len(expand_grid(config)),
                    "first_bbox": expand_grid(config)[0] if expand_grid(config) else None,
                }
                for name, config in self.template.get("cell_grids", {}).items()
            },
            "result": {
                **resolved_data,
                **score_data,
                "warnings": align_meta.warnings,
                "doubt_summary": doubt_summary,
            },
        }

        if save_debug:
            labeling_csv = self.export_cells_for_labeling(aligned_img, all_main_rows, work_id)
            if labeling_csv:
                result_json["labeling_csv"] = labeling_csv
            self.debug_exporter.export(work_id, aligned_img, all_main_rows, all_corrections, result_json, self.template)

        return result_json

    def _process_participant_info(self, aligned_img: np.ndarray) -> Dict[str, str]:
        results = {}
        cell_grids = self.template.get("cell_grids", {})
        
        # Мы обрабатываем только те сетки, которые помечены как текстовые или имеют явные разрешенные символы
        # Обычно это Фамилия, Имя, Отчество, Регион и т.д.
        for grid_name, grid_config in cell_grids.items():
            if "type" not in grid_config and grid_name not in ["participant_surname", "participant_name", "participant_patronymic"]:
                continue
                
            label = grid_name.replace("_", " ").capitalize()
            allowed_chars = grid_config.get("allowed_chars", "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ-")
            field_type = grid_config.get("type", "text")

            bboxes = expand_grid(grid_config)
            if not bboxes:
                continue

            active_bboxes = self._trim_text_grid_to_filled_prefix(aligned_img, bboxes)
            if not active_bboxes:
                results[grid_name] = ""
                continue

            x1 = min(b[0] for b in active_bboxes)
            y1 = min(b[1] for b in active_bboxes)
            x2 = max(b[2] for b in active_bboxes)
            y2 = max(b[3] for b in active_bboxes)

            text = self.classifier.recognize_line(
                aligned_img,
                (x1, y1, x2, y2),
                allowed_chars=allowed_chars,
                is_handwritten=(field_type != "printed")
            )
            text = text.strip().upper()
            # Ъ (твёрдый знак) не встречается в русских именах/отчествах —
            # заменяем на Ь (мягкий знак), с которым он часто путается OCR
            if grid_name in ("participant_name", "participant_patronymic", "participant_surname"):
                text = text.replace("Ъ", "Ь")
            results[grid_name] = text
            
        return results

    def _trim_text_grid_to_filled_prefix(
        self,
        aligned_img: np.ndarray,
        bboxes: list[tuple[int, int, int, int]],
        min_ink: int = 120,
        max_empty_after_text: int = 3,
    ) -> list[tuple[int, int, int, int]]:
        last_filled = -1
        empty_streak = 0
        seen_text = False

        for index, bbox in enumerate(bboxes):
            x1, y1, x2, y2 = bbox
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(aligned_img.shape[1], x2), min(aligned_img.shape[0], y2)
            if x2 <= x1 or y2 <= y1:
                continue

            crop = aligned_img[y1:y2, x1:x2]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
            binary = self.classifier.preprocessor.binarize_for_ocr(gray, is_handwritten=True)
            cleaned = self.classifier._remove_dotted_cell_frame_for_row(binary)
            has_ink = cv2.countNonZero(cleaned) >= min_ink

            if has_ink:
                seen_text = True
                empty_streak = 0
                last_filled = index
            elif seen_text:
                empty_streak += 1
                if empty_streak >= max_empty_after_text:
                    break

        if last_filled < 0:
            return []
        return bboxes[:last_filled + 1]
