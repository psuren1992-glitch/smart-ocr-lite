"""
Регрессионные тесты OCR-пайплайна.

Запуск:
    python tests/test_regression.py

Каждый тест проверяет что после изменений в коде OCR по-прежнему:
1. Выравнивает бланк (4 реперных маркера найдены)
2. Читает конкретные задания с известными ответами
3. Правильно определяет ФИО из верхней части бланка

Добавить новый эталонный бланк:
    1. Положи скан в tests/scans/
    2. Добавь запись в tests/ground_truth.json
    3. Запусти тест — убедись что OK

ВАЖНО: сканы в репо не входят (.gitignore).
Скачай их из общего хранилища или попроси коллег.
"""

import sys
import os
import json
import logging
import time

# Windows cp1251 не поддерживает Unicode символы вне Latin-1
if sys.stdout.encoding and sys.stdout.encoding.lower() in ("cp1251", "cp866", "ascii"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Убираем шум от paddleocr/tesseract
logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from webapp import build_pipeline_for_webapp
from core.answer_key import normalize_answer, answer_variants

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(TESTS_DIR, "..")
GROUND_TRUTH_PATH = os.path.join(TESTS_DIR, "ground_truth.json")


def load_ground_truth():
    with open(GROUND_TRUTH_PATH, encoding="utf-8") as f:
        return json.load(f)["blanks"]


def run_blank(blank_cfg: dict) -> dict:
    scan_path = os.path.join(TESTS_DIR, blank_cfg["file"])
    if not os.path.exists(scan_path):
        return {"skipped": True, "reason": f"Файл не найден: {scan_path}"}

    template_path = os.path.join(
        PROJECT_DIR, "config", "templates", f"{blank_cfg['variant']}.json"
    )
    pipeline = build_pipeline_for_webapp(template_path, debug_dir=None)

    t0 = time.time()
    result = pipeline.process(scan_path, work_id=blank_cfg["id"], save_debug=False)
    elapsed = time.time() - t0

    raw = result.get("result", {}).get("answers_raw", {})
    pinfo = result.get("participant_info", {})
    alignment_ok = result.get("alignment_meta", {}).get("success", False)

    return {
        "skipped": False,
        "elapsed": elapsed,
        "alignment_ok": alignment_ok,
        "answers_raw": raw,
        "participant_surname": pinfo.get("participant_surname", ""),
    }


def check_blank(blank_cfg: dict, actual: dict) -> list[str]:
    """Возвращает список проваленных проверок (пустой = всё OK)."""
    failures = []

    # 1. Выравнивание
    if not actual.get("alignment_ok"):
        failures.append("ALIGNMENT FAILED — реперные маркеры не найдены")

    # 2. Конкретные ожидаемые ответы
    expected = blank_cfg.get("expected_answers", {})
    raw = actual.get("answers_raw", {})
    for task, expected_val in expected.items():
        got = raw.get(str(task), "")
        got_norm = normalize_answer(got)
        exp_variants = answer_variants(expected_val)
        if got_norm not in exp_variants:
            failures.append(
                f"Задание {task}: ожидалось {expected_val!r}, получено {got!r}"
            )

    # 3. ФИО (если задано — проверяем мягко: ожидаемое должно быть подстрокой прочитанного)
    expected_surname = blank_cfg.get("participant_surname", "")
    if expected_surname:
        got_surname = actual.get("participant_surname", "")
        # Принимаем если хотя бы 4 первые буквы совпадают (OCR на именах неточный)
        prefix = expected_surname.upper()[:4]
        if prefix not in got_surname.upper():
            failures.append(
                f"Фамилия: ожидалось {expected_surname!r} (начало), получено {got_surname!r}"
            )

    return failures


def main():
    blanks = load_ground_truth()
    total = len(blanks)
    passed = 0
    skipped = 0
    failed_list = []

    print(f"\n{'='*60}")
    print(f"  Smart OCR Lite — регрессионные тесты ({total} бланков)")
    print(f"{'='*60}\n")

    # Один раз загружаем пайплайн для каждого уникального шаблона
    pipelines: dict = {}

    for blank in blanks:
        bid = blank["id"]
        scan_path = os.path.join(TESTS_DIR, blank["file"])

        if not os.path.exists(scan_path):
            print(f"  SKIP  {bid:<15} — скан отсутствует ({blank['file']})")
            skipped += 1
            continue

        print(f"  RUN   {bid:<15} ({blank['variant']}) ...", end="", flush=True)
        actual = run_blank(blank)

        if actual.get("skipped"):
            print(f"  SKIP — {actual['reason']}")
            skipped += 1
            continue

        failures = check_blank(blank, actual)
        t = f"[{actual['elapsed']:.0f}s]"

        if not failures:
            print(f"  OK  {t}")
            passed += 1
        else:
            print(f"  FAIL {t}")
            for f in failures:
                print(f"        ✗ {f}")
            failed_list.append(bid)

    print(f"\n{'='*60}")
    print(f"  Итого: {passed} OK / {len(failed_list)} FAIL / {skipped} SKIP  (из {total})")
    print(f"{'='*60}\n")

    if failed_list:
        print(f"  Провалившиеся: {', '.join(failed_list)}\n")
        sys.exit(1)
    elif skipped == total:
        print("  Все тесты пропущены — положи сканы в tests/scans/\n")
        sys.exit(0)
    else:
        print("  Все тесты прошли!\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
