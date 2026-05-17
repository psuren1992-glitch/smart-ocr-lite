import json
import os
from typing import Any, Dict


def normalize_answer(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = text.replace(" ", "")
    text = text.replace(".", ",")
    return text


def load_answer_key(path: str) -> Dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    if isinstance(data, dict) and "answers" in data:
        data = data.get("answers", {})

    if not isinstance(data, dict):
        return {}

    answer_key: Dict[str, Any] = {}
    for task, answer in data.items():
        if str(task).startswith("_"):
            continue
        answer_key[str(task)] = answer
    return answer_key


def answer_variants(value: Any) -> list[str]:
    if isinstance(value, list):
        return [normalize_answer(item) for item in value]
    return [normalize_answer(value)]
