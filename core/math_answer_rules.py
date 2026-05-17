import re


class MathAnswerRules:
    """
    Conservative row-level normalization for short math answers.
    """

    def finalize_math_answer(self, text: str, token_entries: list, filled_count: int) -> tuple[str, list[str]]:
        notes: list[str] = []
        normalized = (text or "").replace(".", ",").strip()
        recognized_count = len([entry for entry in token_entries if entry.get("token")])

        if not normalized:
            return "", notes

        if "-" in normalized and not normalized.startswith("-"):
            normalized = "-" + normalized.replace("-", "")
            notes.append("normalized_minus_position")
        elif normalized.count("-") > 1:
            normalized = "-" + normalized.replace("-", "")
            notes.append("normalized_duplicate_minus")

        if normalized.count(",") > 1:
            head, *tail = normalized.split(",")
            normalized = head + "," + "".join(tail)
            notes.append("normalized_duplicate_comma")

        normalized = normalized.rstrip("-,.")

        unknown_filled = [
            entry for entry in token_entries
            if entry.get("filled") and not entry.get("token")
        ]
        has_ambiguous_gap = any(12 <= int(entry.get("ink", 0)) <= 260 for entry in unknown_filled)
        if filled_count != recognized_count:
            notes.append(f"filled_vs_recognized:{filled_count}/{recognized_count}")

        if "," not in normalized and has_ambiguous_gap and filled_count == (len(normalized) + 1):
            if normalized.startswith("0") and len(normalized) >= 2 and normalized[1:].isdigit():
                normalized = f"0,{normalized[1:]}"
                notes.append("inserted_decimal_after_leading_zero")
            elif normalized.startswith("-0") and len(normalized) >= 3 and normalized[2:].isdigit():
                normalized = f"-0,{normalized[2:]}"
                notes.append("inserted_decimal_after_negative_leading_zero")

        if "," not in normalized:
            if normalized.startswith("-0") and len(normalized) >= 3 and normalized[2:].isdigit() and filled_count >= 4:
                decimal_digits = filled_count - 3
                if decimal_digits >= 1:
                    tail = normalized[2:]
                    normalized = f"-0,{tail[-decimal_digits:]}"
                    notes.append("normalized_negative_leading_zero_decimal")
            elif normalized.startswith("0") and len(normalized) >= 2 and normalized[1:].isdigit() and filled_count >= 3:
                decimal_digits = filled_count - 2
                if decimal_digits >= 1:
                    tail = normalized[1:]
                    normalized = f"0,{tail[-decimal_digits:]}"
                    notes.append("normalized_leading_zero_decimal")

        if normalized.startswith(","):
            normalized = "0" + normalized
            notes.append("prefixed_zero_before_comma")
        elif normalized.startswith("-,"):
            normalized = "-0," + normalized[2:]
            notes.append("prefixed_zero_after_minus")

        if not re.fullmatch(r"-?\d+(,\d+)?", normalized):
            notes.append("nonstandard_math_format")

        return normalized, notes
