"""Local recognition of the math answer form used in the 2026/27 school year."""
import json
import os
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from core.alignment import AlignmentService
from core.ocr.paddle_ocr_engine import PaddleOcrEngine
from core.ocr.tesseract_engine import TesseractEngine
from core.ocr.line_recognizer import LineRecognizer
from core.reper_detector import ReperDetector
from core.grid_reader import refine_row

ROOT = Path(__file__).resolve().parents[1]
OCR_VERSION = 'math-grid-v2'


@lru_cache(maxsize=1)
def form_config():
    return json.loads((ROOT / 'config/math_2026_2027.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def classifier():
    paddle = PaddleOcrEngine()
    tesseract = TesseractEngine(tesseract_cmd=os.environ.get('TESSERACT_CMD', r'C:\Program Files\Tesseract-OCR\tesseract.exe'))
    engines = ([paddle] if paddle._ensure_model() else []) + ([tesseract] if tesseract.enabled else [])
    if not engines:
        raise RuntimeError('Не удалось запустить OCR. Проверьте установку Tesseract и PaddleOCR.')
    return LineRecognizer(engines)


def align_form(image):
    cfg = form_config()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    detector = ReperDetector(cfg['marker_zones'], cfg['page_size'])
    markers = detector.detect(binary)
    if len(markers) != 4:
        # Pale photocopied markers need a higher threshold than handwriting.
        _, pale = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        for key, point in detector.detect(pale).items():
            markers.setdefault(key, point)
    if len(markers) != 4:
        raise ValueError('Не найдены четыре угловые метки. Нужна ручная проверка или новый скан.')
    height, width = gray.shape
    if (abs(markers['top_left'][1] - markers['top_right'][1]) > height * .04
            or abs(markers['bottom_left'][1] - markers['bottom_right'][1]) > height * .04
            or markers['top_right'][0] - markers['top_left'][0] < width * .5):
        raise ValueError('Метки образуют неверную геометрию. Проверьте ориентацию и качество скана.')
    aligned, _ = AlignmentService(*cfg['page_size'], cfg['markers']).align(image, markers)
    return aligned


def write_image(path, image):
    # imencode/tofile also supports Cyrillic paths on Windows.
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise ValueError('Не удалось сохранить изображение')
    encoded.tofile(str(path))


def answer_boxes():
    cfg = form_config()
    result = {}
    for block in cfg['answers']:
        for task, y in zip(block['tasks'], block['centers']):
            result[str(task)] = [block['x1'], y - 31, block['x2'], y + 31]
    return result


def clean_grid(image, bbox, count):
    x1, y1, x2, y2 = bbox
    crop = image[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    cleaned = np.full_like(crop, 255)
    last_filled = -1
    for index in range(count):
        left = round(index * width / count) + 5
        right = round((index + 1) * width / count) - 5
        cell = gray[6:height-6, left:right]
        _, binary = cv2.threshold(cell, 180, 255, cv2.THRESH_BINARY_INV)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
        mask = np.zeros_like(binary)
        for k in range(1, n):
            _, _, w, h, area = stats[k]
            # Dotted frames consist of tiny disconnected components.
            if area >= 35 and (w >= 10 or h >= 10):
                mask[labels == k] = 255
        if cv2.countNonZero(mask):
            last_filled = index
            cleaned[6:height-6, left:right][mask > 0] = 0
    return cleaned, last_filled


def read_row(engine, image, bbox, count, task=0):
    cleaned, last = clean_grid(image, bbox, count)
    if last < 0:
        return '', []
    height, width = cleaned.shape[:2]
    # Do not pass trailing empty cells to a language model.
    line = cleaned[:, :round((last+1)*width/count)]
    text = engine.recognize(line, (0, 0, line.shape[1], height),
                            allowed_chars='0123456789-,.', is_handwritten=True)
    text = text.replace(' ', '').replace('.', ',')
    if any(c not in '0123456789-,' for c in text):
        text = ''
    def wider():
        x1, y1, x2, y2 = bbox
        return clean_grid(image, (x1, max(0, y1-7), x2, min(image.shape[0], y2+7)), count)[0]
    return refine_row(engine, cleaned, count, text, wider=wider)


def recognize_page(image, folder):
    cfg = form_config()
    aligned = align_form(image)
    write_image(folder / 'scan.png', aligned)
    engine = classifier()
    answers, notes = {}, {}
    for task, box in answer_boxes().items():
        x1, y1, x2, y2 = box
        write_image(folder / f'answer_{task}.png', aligned[y1:y2, x1:x2])
        answers[task], notes[task] = read_row(engine, aligned, box, 17, int(task))

    names = []
    letters = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ-'
    for box in cfg['name_boxes']:
        clean, last = clean_grid(aligned, box, 30)
        if last >= 0:
            right = round((last+1)*clean.shape[1]/30)
            names.append(engine.recognize(clean, (0, 0, right, clean.shape[0]), allowed_chars=letters, is_handwritten=True))

    corrections = []
    for block in cfg['corrections']:
        for y in block['centers']:
            task_box = [block['task_x1'], y-28, block['task_x2'], y+28]
            answer_box = [block['answer_x1'], y-28, block['answer_x2'], y+28]
            task, _ = read_row(engine, aligned, task_box, 2)
            answer, _ = read_row(engine, aligned, answer_box, 17)
            if task or answer:
                corrections.append({'task': task, 'answer': answer})
    x1, y1, x2, y2 = cfg['correction_box']
    write_image(folder / 'corrections.png', aligned[y1:y2, x1:x2])
    return {'name': ' '.join(filter(None, names)), 'answers': answers,
            'raw': answers.copy(), 'notes': notes, 'corrections': corrections,
            'reviewed': False, 'variant': '1', 'status': 'ready', 'ocr_version': OCR_VERSION}
