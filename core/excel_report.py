import os
import zipfile
from datetime import datetime
from typing import Any, Dict, Iterable, List
from xml.sax.saxutils import escape


def _col_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _cell(ref: str, value: Any, style: int = 0) -> str:
    style_attr = f' s="{style}"' if style else ""
    if value is None:
        value = ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t>{text}</t></is></c>'


def _row(row_index: int, values: Iterable[Any], style: int = 0) -> str:
    cells = []
    for col_index, value in enumerate(values, start=1):
        cells.append(_cell(f"{_col_name(col_index)}{row_index}", value, style))
    return f'<row r="{row_index}">{"".join(cells)}</row>'


def _task_sort_key(task: str) -> tuple[int, str]:
    try:
        return int(task), task
    except ValueError:
        return 10_000, task


class ExcelReportGenerator:
    def build_rows(self, result_json: Dict[str, Any]) -> List[List[Any]]:
        result = result_json.get("result", {})
        answers = result.get("answers_final") or result.get("answers_raw") or {}
        matched = result.get("matched_keys", {})
        doubtful = result.get("doubtful_cells", [])

        doubtful_by_task: Dict[str, List[str]] = {}
        for item in doubtful:
            task = str(item.get("task", ""))
            if not task:
                continue
            doubtful_by_task.setdefault(task, []).append(
                f"cell {item.get('cell_index', '')}: {item.get('reason', '')}"
            )

        tasks = sorted(set(answers.keys()) | set(matched.keys()), key=_task_sort_key)

        info = result_json.get("participant_info", {})
        surname = info.get("participant_surname", "")
        name = info.get("participant_name", "")
        patronymic = info.get("participant_patronymic", "")
        participant_full = f"{surname} {name} {patronymic}".strip()

        rows: List[List[Any]] = [
            ["Smart OCR: результаты проверки"],
            ["ID работы", result_json.get("work_id", "")],
            ["Участник", participant_full],
            ["Файл", result_json.get("source_file", "")],
            ["Шаблон", result_json.get("template_id", "")],
            ["Дата экспорта", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            ["Балл", result.get("correct_count", 0), "из", result.get("total_tasks", 0)],
            [],
            ["Задание", "Ответ ученика", "Правильный ответ", "Статус", "Балл", "Сомнения"],
        ]

        for task in tasks:
            match = matched.get(str(task), {})
            student = match.get("student", answers.get(str(task), ""))
            correct = match.get("correct", "")
            if str(task) in matched:
                ok = bool(match.get("is_correct"))
                status = "Верно" if ok else "Ошибка"
                score = 1 if ok else 0
            else:
                status = "Нет ключа"
                score = ""

            rows.append([
                task,
                student,
                correct,
                status,
                score,
                "; ".join(doubtful_by_task.get(str(task), [])),
            ])

        return rows

    def generate_result_xlsx(self, result_json: Dict[str, Any], output_path: str) -> str:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        rows = self.build_rows(result_json)
        sheet_rows = []
        for index, values in enumerate(rows, start=1):
            # Заголовок (1) и шапка таблицы (9) жирным
            style = 1 if index in (1, 9) else 0
            sheet_rows.append(_row(index, values, style=style))

        worksheet = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="9" topLeftCell="A10" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <cols>
    <col min="1" max="1" width="12" customWidth="1"/>
    <col min="2" max="3" width="22" customWidth="1"/>
    <col min="4" max="5" width="14" customWidth="1"/>
    <col min="6" max="6" width="48" customWidth="1"/>
  </cols>
  <sheetData>{"".join(sheet_rows)}</sheetData>
</worksheet>'''

        workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Результаты" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''

        workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''

        root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''

        content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''

        styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" applyFont="1"/></cellXfs>
</styleSheet>'''

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", root_rels)
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            archive.writestr("xl/worksheets/sheet1.xml", worksheet)
            archive.writestr("xl/styles.xml", styles)

        return output_path
