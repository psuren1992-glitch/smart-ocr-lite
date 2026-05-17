import logging
import re
from typing import Any, Dict, List, Tuple

from core.answer_key import answer_variants, normalize_answer
from core.corrections_reader import CorrectionRow
from core.models.data_models import RowResult
from core.thresholds import ResolverThresholds, get_thresholds

logger = logging.getLogger(__name__)


class AnswerResolver:
    def __init__(
        self,
        classifier=None,
        answer_key: Dict[str, Any] | None = None,
        enable_math_answer_healing: bool = True,
        enable_answer_key_guidance: bool = True,
        thresholds: ResolverThresholds | None = None,
    ):
        self.classifier = classifier
        self.answer_key = answer_key or {}
        self.enable_math_answer_healing = enable_math_answer_healing
        self.enable_answer_key_guidance = enable_answer_key_guidance
        self.t = thresholds or get_thresholds().resolver

    def _normalize_symbol(self, symbol: str) -> str:
        if symbol is None:
            return ""
        text = normalize_answer(symbol)
        return text if len(text) == 1 and text in "0123456789-,." else ""

    def _best_nonempty_candidate(self, cell) -> Tuple[str, float, str]:
        for hypothesis in cell.top_candidates or []:
            symbol = self._normalize_symbol(hypothesis.symbol)
            if symbol:
                return symbol, float(hypothesis.confidence), str(hypothesis.source)
        return "", 0.0, ""

    def _task_accepts_only_integers(self, task: int) -> bool:
        variants = answer_variants(self.answer_key.get(str(task), ""))
        if not variants:
            return False
        return all(re.fullmatch(r"-?\d+", variant) for variant in variants)

    def _get_active_cells(self, cells) -> list:
        cell_list = list(cells or [])
        active_indices = []
        for index, cell in enumerate(cell_list):
            fallback_symbol, _, _ = self._best_nonempty_candidate(cell)
            if cell.best_symbol or fallback_symbol or cell.is_doubtful:
                active_indices.append(index)

        if not active_indices:
            return cell_list

        start_idx = min(active_indices)
        end_idx = max(active_indices)
        return cell_list[start_idx:end_idx + 1]

    def _cell_score_map(self, cell) -> tuple[Dict[str, float], bool]:
        score_map: Dict[str, float] = {}
        best_symbol = self._normalize_symbol(cell.best_symbol)
        if best_symbol:
            score_map[best_symbol] = max(score_map.get(best_symbol, 0.0), max(0.01, float(cell.confidence or 0.0)))

        for hypothesis in cell.top_candidates or []:
            symbol = self._normalize_symbol(hypothesis.symbol)
            if not symbol:
                continue
            score_map[symbol] = max(score_map.get(symbol, 0.0), max(0.01, float(hypothesis.confidence)))

        has_signal = bool(score_map) or bool(cell.is_doubtful)
        return score_map, has_signal

    def _score_variant_against_cells(self, cells, variant: str) -> float:
        tokens = list(normalize_answer(variant))
        if not tokens:
            return -1.0

        active_cells = self._get_active_cells(cells)
        n = len(active_cells)
        m = len(tokens)
        if n == 0:
            return -1.0

        # Pre-calculate score maps to avoid redundant calls in the inner loop
        cell_meta = []
        for cell in active_cells:
            cell_meta.append(self._cell_score_map(cell))

        negative_inf = -10**9
        dp = [[negative_inf] * (m + 1) for _ in range(n + 1)]
        dp[0][0] = 0.0

        for i in range(n + 1):
            score_map, has_signal = cell_meta[i] if i < n else ({}, False)
            skip_penalty = self.t.skip_cell_penalty_signal if has_signal else self.t.skip_cell_penalty_no_signal
            
            for j in range(m + 1):
                if dp[i][j] <= negative_inf / 2:
                    continue

                # Skip current cell (i) and keep current token (j)
                if i < n:
                    if dp[i][j] + skip_penalty > dp[i + 1][j]:
                        dp[i + 1][j] = dp[i][j] + skip_penalty

                # Match current cell (i) with current token (j)
                if i < n and j < m:
                    token = tokens[j]
                    if token in score_map:
                        match_score = self.t.match_base_score + score_map[token]
                    else:
                        match_score = self.t.mismatch_penalty_signal if has_signal else self.t.mismatch_penalty_no_signal
                    if dp[i][j] + match_score > dp[i + 1][j + 1]:
                        dp[i + 1][j + 1] = dp[i][j] + match_score

                # Skip current token (j) and keep current cell (i)
                if j < m:
                    token = tokens[j]
                    skip_token_penalty = self.t.skip_token_penalty_comma_dash if token in ",-" else self.t.skip_token_penalty_other
                    if dp[i][j] + skip_token_penalty > dp[i][j + 1]:
                        dp[i][j + 1] = dp[i][j] + skip_token_penalty

        best_score = max(dp[i][m] for i in range(n + 1))
        return best_score / max(m, 1)

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        if not s2:
            return len(s1)
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        return previous_row[-1]

    def _apply_key_bias(
        self,
        task_number: int,
        cells,
        healed_answer: str,
        notes: List[str],
        filled_count: int,
        recognized_count: int,
    ) -> tuple[str, List[str]]:
        if not self.enable_answer_key_guidance:
            return healed_answer, notes

        variants = answer_variants(self.answer_key.get(str(task_number), ""))
        if not variants:
            return healed_answer, notes

        healed_norm = normalize_answer(healed_answer)
        if healed_norm in variants:
            return healed_answer, notes

        has_uncertainty = (
            filled_count != recognized_count
            or not healed_norm
            or any("nonstandard" in note or "filled_vs_recognized" in note or "gap_filled" in note for note in notes)
            or any(getattr(cell, "is_doubtful", False) for cell in cells or [])
        )
        if not has_uncertainty:
            return healed_answer, notes

        # Conservative one-edit plausible bias:
        # 1. distance <= 1
        # 2. plausible symbols in cells (checked via DP score)
        # 3. only when the OCR result is already uncertain

        current_score = self._score_variant_against_cells(cells, healed_norm) if healed_norm else -1.0
        best_bias_variant = None
        best_bias_score = -1.0

        for variant in variants:
            dist = self._levenshtein_distance(healed_norm, variant)
            if dist > self.t.lev_distance_max:
                continue

            score = self._score_variant_against_cells(cells, variant)

            # We consider this variant if it's plausible:
            # 1. Absolute score is decent
            # 2. Score is not much worse than current OCR score
            if score >= self.t.key_bias_score_min and score >= (current_score - self.t.key_bias_score_delta):
                if score > best_bias_score:
                    best_bias_score = score
                    best_bias_variant = variant

        # Apply bias if we found a good variant that is different from current
        if best_bias_variant and best_bias_variant != healed_norm:
            notes = list(notes) + [f"biased_to_match_key:{best_bias_variant}", f"bias_score:{best_bias_score:.2f}"]
            return best_bias_variant, notes

        return healed_answer, notes

    def _heal_math_answer(
        self,
        task_number: int,
        cells,
        answer_text: str,
        existing_notes: List[str] | None = None,
        filled_count: int | None = None,
        recognized_count: int | None = None,
    ) -> Tuple[str, List[str]]:
        notes = list(existing_notes or [])
        cell_list = list(cells or [])
        if filled_count is None:
            filled_count = 0
            for cell in cell_list:
                fallback_symbol, _, _ = self._best_nonempty_candidate(cell)
                if (cell.best_symbol or fallback_symbol or cell.is_doubtful) and not getattr(cell, "is_crossed_out", False):
                    filled_count += 1
        if recognized_count is None:
            recognized_count = sum(1 for cell in cell_list if self._normalize_symbol(cell.best_symbol))

        active_cells = self._get_active_cells(cell_list)
        if not active_cells:
            active_cells = cell_list

        token_entries = []
        gap_entries = []
        for index, cell in enumerate(active_cells):
            current_symbol = self._normalize_symbol(cell.best_symbol)
            fallback_symbol, fallback_conf, fallback_source = self._best_nonempty_candidate(cell)

            entry = {
                "cell_index": index,
                "symbol": current_symbol,
                "confidence": float(cell.confidence or 0.0),
                "source": "cell_best",
                "is_gap": False,
            }

            if not current_symbol and fallback_symbol:
                entry["symbol"] = fallback_symbol
                entry["confidence"] = fallback_conf
                entry["source"] = fallback_source or "top_candidate"
                entry["is_gap"] = True
                gap_entries.append(entry)

            if entry["symbol"]:
                token_entries.append(entry)

        healed = normalize_answer(answer_text)
        if gap_entries and filled_count > recognized_count:
            healed = "".join(item["symbol"] for item in token_entries).rstrip("-,.")
            notes.append("gap_filled_from_top_candidates")

        gap_count = max(0, filled_count - recognized_count)
        has_gap = gap_count > 0 or any(item["is_gap"] for item in gap_entries)

        if "," not in healed and "." not in healed and has_gap:
            unsigned = healed[1:] if healed.startswith("-") else healed
            sign = "-" if healed.startswith("-") else ""
            if unsigned.startswith("0") and len(unsigned) >= 2 and unsigned.isdigit():
                healed = f"{sign}0,{unsigned[1:]}"
                notes.append("inserted_comma_from_gap")

        healed = healed.replace(".", ",")
        healed = healed.rstrip("-,.")

        comma_entries = [item for item in token_entries if item["symbol"] == ","]
        if self._task_accepts_only_integers(task_number) and "," in healed:
            low_conf_comma = any(item['confidence'] < self.t.comma_confidence_threshold for item in comma_entries) or 'inserted_comma_from_gap' in notes
            if low_conf_comma:
                healed = healed.replace(",", "")
                notes.append("dropped_comma_for_integer_task")

        if healed.startswith(","):
            healed = "0" + healed
            notes.append("prefixed_zero_before_comma")
        elif healed.startswith("-,"):
            healed = "-0," + healed[2:]
            notes.append("prefixed_zero_after_minus")

        if not re.fullmatch(r"-?\d+(,\d+)?", healed):
            notes.append("nonstandard_math_format")

        deduped_notes: List[str] = []
        seen = set()
        for note in notes:
            if note not in seen:
                seen.add(note)
                deduped_notes.append(note)

        return healed, deduped_notes

    def resolve(
        self,
        main_rows: List[RowResult],
        corrections: List[CorrectionRow],
        aligned_image=None,
    ) -> Dict[str, Any]:
        answers_raw = {}
        answers_final = {}
        doubtful_cells = []
        applied_corrections = []
        ignored_corrections = []
        row_diagnostics_map = {}
        row_map = {}
        final_answer_sources = {}

        for row in main_rows:
            task = row.task_number
            if task == -1:
                continue
            task_str = str(task)
            row_map[task_str] = row

            row_answer = getattr(row, "answer_text", "").strip()
            if row_answer:
                raw_answer = row_answer
            else:
                raw_answer = "".join([c.best_symbol for c in row.cells if not c.is_empty]).rstrip()

            answers_raw[str(task)] = raw_answer
            final_answer_sources[task_str] = {
                "task": task,
                "answer_text": raw_answer,
                "cells": row.cells,
                "filled_cells_count": getattr(row, "filled_cells_count", 0),
                "recognized_cells_count": getattr(row, "recognized_cells_count", 0),
                "validation_notes": list(getattr(row, "validation_notes", []) or []),
                "source_kind": "main",
            }

            for cell in row.cells:
                if cell.is_doubtful:
                    doubtful_cells.append(
                        {
                            "task": task,
                            "cell_index": cell.cell_index,
                            "symbol": cell.best_symbol,
                            "reason": cell.doubt_reason,
                        }
                    )

        for corr in corrections:
            task_str = str(corr.task_number)
            if self.classifier is not None and aligned_image is not None:
                new_ans_str = self.classifier.classify_row(aligned_image, corr.answer_cells)
            else:
                new_ans_str = "".join([c.best_symbol for c in corr.answer_cells]).rstrip()

            corr_info = {
                "task": corr.task_number,
                "new_answer": new_ans_str,
                "confidence": corr.task_confidence,
                "warnings": corr.warnings,
            }

            if corr.is_valid and task_str in final_answer_sources:
                prev_answer = final_answer_sources[task_str]["answer_text"]
                logger.info("Применена замена для задания %s: '%s' -> '%s'", task_str, prev_answer, new_ans_str)
                final_answer_sources[task_str] = {
                    "task": corr.task_number,
                    "answer_text": new_ans_str,
                    "cells": corr.answer_cells,
                    "filled_cells_count": sum(1 for cell in corr.answer_cells if self._normalize_symbol(cell.best_symbol) or self._best_nonempty_candidate(cell)[0] or cell.is_doubtful),
                    "recognized_cells_count": sum(1 for cell in corr.answer_cells if self._normalize_symbol(cell.best_symbol)),
                    "validation_notes": list(corr.warnings or []) + ["correction_applied"],
                    "source_kind": "correction",
                }
                applied_corrections.append(corr_info)
            else:
                logger.warning(
                    "Замена для задания %s сохранена, но не применена (is_valid=%s).",
                    task_str,
                    corr.is_valid,
                )
                ignored_corrections.append(corr_info)

            for cell in corr.task_cells + corr.answer_cells:
                if cell.is_doubtful:
                    doubtful_cells.append(
                        {
                            "task": f"correction_{corr.task_number}",
                            "cell_index": cell.cell_index,
                            "symbol": cell.best_symbol,
                            "reason": cell.doubt_reason,
                        }
                    )

        row_diagnostics = []
        for task_str, source_info in final_answer_sources.items():
            task = source_info["task"]
            raw_answer = answers_raw.get(task_str, source_info["answer_text"])
            if self.enable_math_answer_healing:
                healed_answer, heal_notes = self._heal_math_answer(
                    task_number=task,
                    cells=source_info["cells"],
                    answer_text=source_info["answer_text"],
                    existing_notes=source_info["validation_notes"],
                    filled_count=source_info["filled_cells_count"],
                    recognized_count=source_info["recognized_cells_count"],
                )
            else:
                healed_answer = source_info["answer_text"]
                heal_notes = list(source_info["validation_notes"] or [])

            healed_answer, heal_notes = self._apply_key_bias(
                task_number=task,
                cells=source_info["cells"],
                healed_answer=healed_answer,
                notes=heal_notes,
                filled_count=source_info["filled_cells_count"],
                recognized_count=source_info["recognized_cells_count"],
            )

            is_biased = any("biased_to_match_key" in note for note in heal_notes)
            if is_biased:
                source_info["source_kind"] = "biased_to_key"

            answers_final[task_str] = healed_answer
            row_diagnostics_map[task_str] = {
                "task": task,
                "raw_answer_text": raw_answer,
                "answer_text": healed_answer,
                "filled_cells_count": source_info["filled_cells_count"],
                "recognized_cells_count": source_info["recognized_cells_count"],
                "validation_notes": heal_notes,
                "source_kind": source_info["source_kind"],
            }

        for task_str in sorted(row_diagnostics_map, key=lambda value: int(value) if str(value).isdigit() else 10_000):
            row_diagnostics.append(row_diagnostics_map[task_str])

        return {
            "answers_raw": answers_raw,
            "answers_final": answers_final,
            "corrections_applied": applied_corrections,
            "corrections_ignored": ignored_corrections,
            "doubtful_cells": doubtful_cells,
            "row_diagnostics": row_diagnostics,
        }
