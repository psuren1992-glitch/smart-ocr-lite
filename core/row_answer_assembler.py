import cv2


class RowAnswerAssembler:
    def __init__(self, cell_classifier_flow, shape_rules, finalize_math_answer, ai_row_reader=None):
        self.ccf = cell_classifier_flow
        self.shape_rules = shape_rules
        self.finalize_math_answer = finalize_math_answer
        self.ai_row_reader = ai_row_reader

    def _build_row_bbox(self, row_cells, start_idx: int, end_idx: int):
        selected = row_cells[start_idx:end_idx + 1]
        if not selected:
            return None
        x1 = min(cell.inner_bbox[0] for cell in selected)
        y1 = min(cell.inner_bbox[1] for cell in selected)
        x2 = max(cell.inner_bbox[2] for cell in selected)
        y2 = max(cell.inner_bbox[3] for cell in selected)
        return (x1, y1, x2, y2)

    def _normalize_ai_text(self, text: str, allowed_chars: str) -> str:
        if not text:
            return ""
        normalized = text.replace(" ", "").replace("\n", "").replace(".", ",").strip()
        if allowed_chars:
            allowed = set(allowed_chars)
            normalized = "".join(ch for ch in normalized if ch in allowed)
        return normalized

    def _levenshtein_distance(self, left: str, right: str) -> int:
        if left == right:
            return 0
        if not left:
            return len(right)
        if not right:
            return len(left)

        prev = list(range(len(right) + 1))
        for i, lch in enumerate(left, start=1):
            curr = [i]
            for j, rch in enumerate(right, start=1):
                cost = 0 if lch == rch else 1
                curr.append(min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + cost,
                ))
            prev = curr
        return prev[-1]

    def _is_single_seven_to_one_fix(self, current_text: str, ai_text: str, token_entries) -> bool:
        if len(current_text) != len(ai_text) or current_text == ai_text:
            return False

        diffs = [
            (index, left, right)
            for index, (left, right) in enumerate(zip(current_text, ai_text))
            if left != right
        ]
        if len(diffs) != 1:
            return False

        diff_index, left, right = diffs[0]
        if (left, right) != ("7", "1"):
            return False

        text_entries = [entry for entry in token_entries if entry.get("token")]
        if diff_index >= len(text_entries):
            return False

        entry = text_entries[diff_index]
        if entry.get("has_seven_mid_crossbar"):
            return False

        return True

    def _should_use_ai_text(
        self,
        current_text: str,
        ai_text: str,
        *,
        filled_count: int,
        recognized_count: int,
        active_cells,
        token_entries,
    ) -> bool:
        if not ai_text or ai_text == current_text:
            return False
        if filled_count <= 0 or len(ai_text) > filled_count + 1:
            return False

        any_doubtful = any(getattr(cell, "is_doubtful", False) for cell in active_cells)
        has_gap = recognized_count < filled_count or not current_text

        if has_gap:
            return True

        if any_doubtful and self._levenshtein_distance(current_text, ai_text) <= 1:
            return True

        if any_doubtful and any(ch in ai_text for ch in ",-") and not any(ch in current_text for ch in ",-"):
            return True

        if self._is_single_seven_to_one_fix(current_text, ai_text, token_entries):
            return True

        return False

    def classify_row(self, aligned_image, row_cells, allowed_chars="0123456789-,.", row=None) -> str:
        processed_cells = []
        ink_counts = []

        for cell in row_cells:
            binary = self.ccf.preprocess_cell_for_row(aligned_image, cell)
            processed_cells.append(binary)
            ink_counts.append(int(cv2.countNonZero(binary)))

        filled_flags = []
        for count, img in zip(ink_counts, processed_cells):
            looks_like_punct = self.shape_rules.looks_like_minus(img) or self.shape_rules.looks_like_comma(img)
            filled_flags.append(count >= 35 or (count >= 10 and looks_like_punct))

        ink_indices = [index for index, filled in enumerate(filled_flags) if filled]
        if not ink_indices:
            if row is not None:
                row.filled_cells_count = 0
                row.recognized_cells_count = 0
                row.validation_notes = []
            return ""

        first_idx = max(0, ink_indices[0])
        last_idx = min(len(processed_cells) - 1, ink_indices[-1])

        empty_run = 0
        gap_start = None
        for index in range(first_idx, len(filled_flags)):
            if filled_flags[index]:
                empty_run = 0
                gap_start = None
                last_idx = index
            else:
                if gap_start is None:
                    gap_start = index
                empty_run += 1
                if empty_run >= 4:
                    last_idx = gap_start - 1
                    break

        cell_imgs = processed_cells[first_idx:last_idx + 1]
        standard_imgs = [
            self.ccf.preprocess_cell(aligned_image, row_cells[index])
            for index in range(first_idx, last_idx + 1)
        ]

        token_entries = []
        
        # Фильтруем allowed_chars для классификатора цифр
        digit_allowed = "".join(ch for ch in allowed_chars if ch in "0123456789")
        if not digit_allowed:
            digit_allowed = "0123456789"

        for cell_index, (row_img, standard_img) in enumerate(zip(cell_imgs, standard_imgs)):
            entry = {
                "cell_index": first_idx + cell_index,
                "ink": ink_counts[first_idx + cell_index],
                "filled": filled_flags[first_idx + cell_index],
                "token": "",
                "kind": "unknown",
                "has_seven_mid_crossbar": False,
                "looks_like_plain_one": False,
            }
            if cell_index == 0 and self.shape_rules.looks_like_minus(row_img) and "-" in allowed_chars:
                entry["token"] = "-"
                entry["kind"] = "minus"
                token_entries.append(entry)
                continue

            if self.shape_rules.looks_like_comma(row_img) and ("," in allowed_chars or "." in allowed_chars):
                entry["token"] = "," if "," in allowed_chars else "."
                entry["kind"] = "comma"
                token_entries.append(entry)
                continue

            has_crossbar = (
                hasattr(self.shape_rules, "has_seven_mid_crossbar")
                and self.shape_rules.has_seven_mid_crossbar(row_img)
            )
            looks_plain_one = (
                hasattr(self.shape_rules, "looks_like_plain_one")
                and self.shape_rules.looks_like_plain_one(row_img)
            )
            entry["has_seven_mid_crossbar"] = bool(has_crossbar)
            entry["looks_like_plain_one"] = bool(looks_plain_one)

            symbol = self.ccf._classify_digit_cell(standard_img, row_img, allowed_chars=digit_allowed)
            if symbol == "1" and has_crossbar and "7" in digit_allowed:
                symbol = "7"
                entry["kind"] = "digit_shape_seven_crossbar"
                entry["note"] = "seven_mid_crossbar"
            if symbol:
                entry["token"] = symbol
                if entry["kind"] == "unknown":
                    entry["kind"] = "digit"
            token_entries.append(entry)

        text = "".join(entry["token"] for entry in token_entries if entry["token"])
        text = text.rstrip("-,.")

        filled_count = sum(1 for entry in token_entries if entry["filled"])
        recognized_count = len([entry for entry in token_entries if entry["token"]])
        text, validation_notes = self.finalize_math_answer(text, token_entries, filled_count)
        shape_notes = [entry["note"] for entry in token_entries if entry.get("note")]
        validation_notes = list(validation_notes) + shape_notes

        if self.ai_row_reader is not None:
            row_bbox = self._build_row_bbox(row_cells, first_idx, last_idx)
            ai_text = ""
            if row_bbox is not None:
                ai_text = self.ai_row_reader(
                    aligned_image,
                    row_bbox,
                    allowed_chars=allowed_chars,
                    is_handwritten=True,
                )
            ai_text = self._normalize_ai_text(ai_text, allowed_chars)
            active_cells = row_cells[first_idx:last_idx + 1]
            if self._should_use_ai_text(
                text,
                ai_text,
                filled_count=filled_count,
                recognized_count=recognized_count,
                active_cells=active_cells,
                token_entries=token_entries,
            ):
                ai_text, ai_notes = self.finalize_math_answer(ai_text, token_entries, filled_count)
                text = ai_text
                validation_notes = list(validation_notes) + list(ai_notes) + ["ai_row_reread"]

        if row is not None:
            row.filled_cells_count = filled_count
            row.recognized_cells_count = recognized_count
            row.validation_notes = validation_notes

        return text
