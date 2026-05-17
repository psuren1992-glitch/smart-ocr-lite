import json
import logging
import os
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_file, send_from_directory, url_for

from core.answer_key import load_answer_key
from core.excel_report import ExcelReportGenerator
from core.ocr_factory import build_default_symbol_classifier
from core.pdf_loader import PdfLoader
from core.pipeline import DocumentProcessorPipeline


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="ui/templates", static_folder="ui/static")


@app.template_filter("intsort")
def intsort_filter(keys):
    """Sort dict keys as integers (for task numbers 1-19)."""
    try:
        return sorted(keys, key=int)
    except (ValueError, TypeError):
        return sorted(keys)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "data", "uploads")
RESULTS_FOLDER = os.path.join(BASE_DIR, "data", "results")
DEBUG_CROPS = os.path.join(BASE_DIR, "debug_crops")
TEMPLATES_DIR = os.path.join(BASE_DIR, "config", "templates")
ANSWER_KEYS_DIR = os.path.join(BASE_DIR, "config", "answer_keys")

# --- Лимиты ---
# Максимальный размер загружаемого файла: 50 MB
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH_MB", 50)) * 1024 * 1024
# Лимит запросов на один IP: 10 запросов в минуту
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", 10))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", 60))
# Допустимые расширения файлов
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".pdf"}
# Хранилище rate limiter'а: IP -> [(timestamp), ...]
_request_log: dict[str, list[float]] = {}
# ---------------

app.config.update(
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    RESULTS_FOLDER=RESULTS_FOLDER,
    DEBUG_CROPS=DEBUG_CROPS,
    TEMPLATES_DIR=TEMPLATES_DIR,
    ANSWER_KEYS_DIR=ANSWER_KEYS_DIR,
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
)

for folder in [UPLOAD_FOLDER, RESULTS_FOLDER, DEBUG_CROPS, ANSWER_KEYS_DIR]:
    os.makedirs(folder, exist_ok=True)

TESSERACT_CMD = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
DEFAULT_PORT = 5001


def _truthy(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_pipeline_for_webapp(
    template_path: str,
    debug_dir: str = DEBUG_CROPS,
    ocr_truth_mode: bool | None = None,
) -> DocumentProcessorPipeline:
    with open(template_path, "r", encoding="utf-8") as f:
        template_data = json.load(f)

    answer_key_path = os.path.join(app.config["ANSWER_KEYS_DIR"], os.path.basename(template_path))
    answer_key = load_answer_key(answer_key_path)
    use_truth_mode = _truthy(os.environ.get("OCR_TRUTH_MODE")) if ocr_truth_mode is None else bool(ocr_truth_mode)

    classifier = build_default_symbol_classifier(
        tesseract_cmd=TESSERACT_CMD,
        doubt_threshold=0.65,
        include_hog_svm=True,
        include_paddleocr=True,
        include_google_vision=False,
        include_google_docai=False,
    )

    return DocumentProcessorPipeline(
        template_data,
        answer_key,
        classifier,
        debug_dir=debug_dir,
        ocr_truth_mode=use_truth_mode,
    )


def build_debug_files(debug_root: str, work_id: str):
    debug_files = []
    debug_dir = os.path.join(debug_root, work_id)
    for filename, label in [
        ("input.png", "Исходное изображение"),
        ("preprocessed.png", "После предобработки"),
        ("aligned.png", "Выровненный скан"),
        ("row_overlay.png", "Разметка строк и клеток"),
        ("template_cells_overlay.png", "Эталонная карта ячеек"),
        ("meta.json", "Debug JSON"),
    ]:
        if os.path.exists(os.path.join(debug_dir, filename)):
            debug_files.append(
                {
                    "label": label,
                    "url": url_for("custom_static", filename=f"{work_id}/{filename}"),
                }
            )
    return debug_files


def save_result_json(result: dict, work_id: str) -> str:
    result_path = os.path.join(app.config["RESULTS_FOLDER"], f"{work_id}.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
    return result_path


def get_latest_result_summary() -> dict | None:
    results_dir = Path(app.config["RESULTS_FOLDER"])
    candidates = [path for path in results_dir.glob("*.json") if path.is_file()]
    if not candidates:
        return None

    latest_path = max(candidates, key=lambda path: path.stat().st_mtime)
    try:
        with latest_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    first_page = data.get("pages", [{}])[0] if data.get("pages") else data
    participant = first_page.get("participant_info") or data.get("participant_info") or {}
    result_payload = first_page.get("result") or data.get("result") or {}
    source_file = first_page.get("source_file") or data.get("source_file") or latest_path.name

    return {
        "work_id": first_page.get("work_id") or data.get("work_id") or latest_path.stem,
        "source_file": source_file,
        "participant_surname": participant.get("participant_surname") or "",
        "participant_name": participant.get("participant_name") or "",
        "participant_patronymic": participant.get("participant_patronymic") or "",
        "correct_count": result_payload.get("correct_count"),
        "total_tasks": result_payload.get("total_tasks"),
        "processed_at": datetime.fromtimestamp(latest_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
    }


def _uploaded_file_is_empty(file_storage) -> bool:
    if file_storage is None:
        return True

    content_length = getattr(file_storage, "content_length", None)
    if content_length is not None and content_length > 0:
        return False

    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return content_length in (None, 0)

    try:
        current_pos = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(current_pos, os.SEEK_SET)
        return size <= 0
    except (AttributeError, OSError, ValueError):
        return False


def process_pdf_pages(pdf_path: str, work_id: str, pipeline: DocumentProcessorPipeline) -> dict:
    loader = PdfLoader(dpi=300)
    try:
        pages = loader.load_pdf_as_images(pdf_path)
    except FileNotFoundError:
        logger.error("PDF file not found while processing batch: %s", pdf_path)
        raise
    if not pages:
        raise RuntimeError("PDF пуст или не удалось извлечь страницы")

    batch_pages = []
    for page_index, (page_name, page_image) in enumerate(pages, start=1):
        page_work_id = f"{work_id}_p{page_index:02d}"
        temp_img_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{page_work_id}.png")
        try:
            import cv2

            cv2.imwrite(temp_img_path, page_image)
            page_result = pipeline.process(temp_img_path, page_work_id, save_debug=True)
            page_result["source_file"] = page_name
            page_result["page_number"] = page_index
            page_result["page_name"] = page_name
            page_result["batch_parent_id"] = work_id
            save_result_json(page_result, page_work_id)
            batch_pages.append(page_result)
        finally:
            if os.path.exists(temp_img_path):
                os.remove(temp_img_path)

    success_count = sum(1 for page in batch_pages if page.get("result") and page.get("status") != "failed")
    failed_count = len(batch_pages) - success_count
    return {
        "work_id": work_id,
        "timestamp": datetime.now().isoformat(),
        "template_id": pipeline.template.get("template_id"),
        "source_file": os.path.basename(pdf_path),
        "batch": True,
        "page_count": len(batch_pages),
        "success_count": success_count,
        "failed_count": failed_count,
        "pages": batch_pages,
    }


@app.route("/")
def index():
    try:
        templates = [f for f in os.listdir(app.config["TEMPLATES_DIR"]) if f.endswith(".json")]
    except OSError:
        templates = []
    latest_result = get_latest_result_summary()
    return render_template("index.html", templates=templates, latest_result=latest_result)


@app.route("/process", methods=["POST"])
def process_file():
    rate_limit_response = _check_rate_limit()
    if rate_limit_response is not None:
        return rate_limit_response

    if "file" not in request.files:
        return jsonify({"error": "Файл не найден в запросе."}), 400

    file = request.files["file"]
    template_id = request.form.get("template_id")
    if not file.filename:
        return jsonify({"error": "Имя файла не указано."}), 400
    if not template_id:
        return jsonify({"error": "Не указан template_id."}), 400

    work_id = str(uuid.uuid4())[:8]
    file_ext = os.path.splitext(file.filename)[1].lower()

    # Проверка расширения
    if file_ext not in ALLOWED_EXTENSIONS:
        logger.warning("Отклонён файл с недопустимым расширением: %s", file_ext)
        return jsonify({"error": f"Недопустимое расширение файла: {file_ext}. Разрешены: {', '.join(sorted(ALLOWED_EXTENSIONS))}"}), 400

    # Проверка пустого файла
    if _uploaded_file_is_empty(file):
        logger.warning("Отклонён пустой файл: %s", file.filename)
        return jsonify({"error": "Файл пуст. Загрузите непустой файл."}), 400

    save_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{work_id}{file_ext}")
    file.save(save_path)

    try:
        template_filename = template_id if template_id.endswith(".json") else f"{template_id}.json"
        template_path = os.path.join(app.config["TEMPLATES_DIR"], template_filename)
        ocr_truth_mode = _truthy(request.form.get("ocr_truth_mode")) or _truthy(request.args.get("ocr_truth_mode"))
        pipeline = build_pipeline_for_webapp(
            template_path,
            app.config["DEBUG_CROPS"],
            ocr_truth_mode=ocr_truth_mode,
        )

        if file_ext == ".pdf":
            result = process_pdf_pages(save_path, work_id, pipeline)
        else:
            result = pipeline.process(save_path, work_id, save_debug=True)

        save_result_json(result, work_id)
        return redirect(url_for("result_view", work_id=work_id))
    except FileNotFoundError as exc:
        logger.error("Файл не найден: %s", exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error("Ошибка обработки файла", exc_info=True)
        return render_template("results.html", work_id=work_id, error=str(exc))


@app.route("/result/<work_id>")
def result_view(work_id):
    result_path = os.path.join(app.config["RESULTS_FOLDER"], f"{work_id}.json")
    if not os.path.exists(result_path):
        return render_template("results.html", work_id=work_id, error="Результаты не найдены")

    with open(result_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("pages"):
        for page in data["pages"]:
            page_work_id = page.get("work_id", "")
            page["debug_files"] = build_debug_files(app.config["DEBUG_CROPS"], page_work_id)
            page["result_url"] = url_for("result_view", work_id=page_work_id)
            page["export_url"] = url_for("export_xlsx", work_id=page_work_id)
        debug_files = []
    else:
        debug_files = build_debug_files(app.config["DEBUG_CROPS"], work_id)

    return render_template("results.html", data=data, work_id=work_id, debug_files=debug_files)


@app.route("/result/<work_id>/export.xlsx")
def export_xlsx(work_id):
    result_path = os.path.join(app.config["RESULTS_FOLDER"], f"{work_id}.json")
    if not os.path.exists(result_path):
        return render_template("results.html", work_id=work_id, error="Результаты не найдены")

    with open(result_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    export_dir = os.path.join(app.config["RESULTS_FOLDER"], "xlsx")
    os.makedirs(export_dir, exist_ok=True)

    if data.get("pages"):
        zip_path = os.path.join(export_dir, f"{work_id}_results.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for page in data["pages"]:
                if page.get("status") == "failed" or not page.get("result"):
                    continue
                page_work_id = page.get("work_id")
                page_xlsx_path = os.path.join(export_dir, f"{page_work_id}_results.xlsx")
                ExcelReportGenerator().generate_result_xlsx(page, page_xlsx_path)
                archive.write(page_xlsx_path, arcname=os.path.basename(page_xlsx_path))
        return send_file(zip_path, as_attachment=True, download_name=f"{work_id}_results.zip", mimetype="application/zip")

    output_path = os.path.join(export_dir, f"{work_id}_results.xlsx")
    ExcelReportGenerator().generate_result_xlsx(data, output_path)
    return send_file(
        output_path,
        as_attachment=True,
        download_name=f"{work_id}_results.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/templates")
def list_templates_api():
    templates = []
    for fname in sorted(os.listdir(app.config["TEMPLATES_DIR"])):
        if not fname.endswith(".json"):
            continue
        tid = fname.replace(".json", "")
        name = tid  # fallback
        try:
            with open(os.path.join(app.config["TEMPLATES_DIR"], fname), encoding="utf-8") as fh:
                data = json.load(fh)
                name = data.get("template_name", tid)
        except Exception:
            pass
        # Группа = часть имени до " — " (или "Другие шаблоны" если разделителя нет)
        group = name.split(" — ")[0] if " — " in name else "Другие шаблоны"
        templates.append({"id": tid, "name": name, "group": group})
    # Сортировка: варианты 2026 первыми (по группе), затем остальные; внутри — по имени
    templates.sort(key=lambda t: (0 if "2026" in t["id"] else 1, t["group"], t["name"]))
    return jsonify(templates)


@app.route("/editor")
def template_editor():
    return render_template("editor.html")


@app.route("/debug_crops/<path:filename>")
def custom_static(filename):
    return send_from_directory(app.config["DEBUG_CROPS"], filename)


@app.after_request
def add_no_cache_headers(response):
    if response.content_type and "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# --- In-memory rate limiter ---

def _rate_limit_exceeded(ip: str) -> bool:
    now = datetime.now().timestamp()
    window = RATE_LIMIT_WINDOW_SECONDS
    limit = RATE_LIMIT_PER_MINUTE

    log = _request_log.setdefault(ip, [])
    # Сдвигаем окно — удаляем записи старше window секунд
    cutoff = now - window
    _request_log[ip] = [t for t in log if t > cutoff]

    if len(_request_log[ip]) >= limit:
        return True

    _request_log[ip].append(now)
    return False


def _check_rate_limit():
    ip = request.remote_addr or "unknown"
    if _rate_limit_exceeded(ip):
        logger.warning("Rate limit exceeded for IP %s", ip)
        return jsonify({"error": "Too many requests. Try again later."}), 429
    return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_mode, use_reloader=False)
