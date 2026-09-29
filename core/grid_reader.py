"""Geometry helpers for numeric, one-symbol-per-cell answer rows."""
import cv2
import numpy as np


def inspect_cells(cleaned, count):
    height, width = cleaned.shape[:2]
    cells = []
    for index in range(count):
        cell = cleaned[:, round(index * width / count):round((index + 1) * width / count)]
        ys, xs = np.where(cell[:, :, 0] < 128)
        if not len(xs):
            continue
        box = (int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1))
        cells.append({'index': index, 'image': cell, 'box': box, 'symbol': None})
    tall = [c for c in cells if c['box'][3] - c['box'][1] >= height * .45]
    if not tall:
        return cells
    ref_height = float(np.median([c['box'][3] - c['box'][1] for c in tall]))
    ref_width = float(np.median([c['box'][2] - c['box'][0] for c in tall]))
    ref_top = float(np.median([c['box'][1] for c in tall]))
    ref_bottom = float(np.median([c['box'][3] for c in tall]))
    for position, c in enumerate(cells):
        x1, y1, x2, y2 = c['box']
        w, h = x2 - x1, y2 - y1
        if position == 0 and w >= 1.5 * h and h <= ref_height * .4:
            c['symbol'] = '-'
        elif (0 < position < len(cells) - 1 and w <= ref_width * .65
              and h <= ref_height * .85 and y1 >= ref_top + 8 and y2 >= ref_bottom - 8):
            c['symbol'] = ','
    return cells


def assemble(cells, digits):
    if not digits.isascii() or not digits.isdigit():
        return None
    if len(digits) != sum(c['symbol'] is None for c in cells):
        return None
    values = iter(digits)
    return ''.join(c['symbol'] if c['symbol'] is not None else next(values) for c in cells)


def compact_digits(cells):
    pieces = []
    for c in cells:
        if c['symbol'] is not None:
            continue
        x1, _, x2, _ = c['box']
        # Preserve vertical position and the natural handwritten shape.
        piece = c['image'][:, x1:x2]
        pieces.append(cv2.copyMakeBorder(piece, 0, 0, 5, 5, cv2.BORDER_CONSTANT, value=(255, 255, 255)))
    return np.concatenate(pieces, axis=1) if pieces else None


def digit_text(text):
    if any(c not in '0123456789-,.' for c in text):
        return ''
    return ''.join(c for c in text if c in '0123456789')


def read_compact(engine, cells):
    compact = compact_digits(cells)
    if compact is None:
        return None
    height, width = compact.shape[:2]
    text = engine.recognize(compact, (0, 0, width, height),
                            allowed_chars='0123456789-,.', is_handwritten=True)
    return assemble(cells, digit_text(text.replace(' ', '')))


def refine_row(engine, cleaned, count, raw, wider=None):
    """Use cell geometry as evidence, never task numbers or answer keys."""
    cells = inspect_cells(cleaned, count)
    if not cells:
        return raw, []
    indices = [c['index'] for c in cells]
    symbols = [c['symbol'] for c in cells]
    if indices != list(range(len(cells))) or symbols.count(',') > 1:
        return raw, ['Неровное заполнение клеток; сверьте запись по скану']
    digits = digit_text(raw)
    expected_digits = sum(s is None for s in symbols)
    mismatch = len(digits) != expected_digits
    has_signs = any(s is not None for s in symbols)
    candidate = read_compact(engine, cells)
    notes = []
    if mismatch:
        notes.append('Число прочитанных цифр не совпало с заполненными клетками')
    # A wider crop may recover clipped strokes, but only with the same cell layout.
    if candidate is None and (mismatch or has_signs) and wider is not None:
        wide_cells = inspect_cells(wider(), count)
        layout = lambda items: [(c['index'], c['symbol']) for c in items]
        if layout(wide_cells) == layout(cells):
            candidate = read_compact(engine, wide_cells)
    result = raw
    if has_signs or mismatch:
        if candidate is not None:
            result = candidate
        elif has_signs:
            result = assemble(cells, digits) or raw
    # Do not remove punctuation just because it lies between cells, or overwrite
    # an equally plausible digit sequence merely because a second OCR disagrees.
    if candidate is not None and candidate != raw:
        notes.append(f'Чтение строки: {raw or "не прочитано"}; по клеткам: {candidate}. Сверьте со сканом')
    elif result != raw:
        notes.append('Знаки уточнены по клеткам; сверьте со сканом')
    if not result:
        notes.append('В клетках есть запись, но ответ не распознан')
    return result, notes
