"""Desktop check of mobile marker geometry on bundled, unfilled references.

This checks calibration and empty-cell filtering, not Android runtime or handwriting accuracy.
"""
import json
from pathlib import Path
import cv2
import fitz
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'app/src/main/assets'
OUT = ROOT / 'qa-desktop'
OUT.mkdir(exist_ok=True)
forms = json.loads((ASSETS / 'forms.json').read_text(encoding='utf-8'))
cases = [
    ('oge_math', 'oge-math-answer1-2026.pdf', 0),
    ('oge_russian', 'oge-russian-answer1-2026.pdf', 0),
    ('ege_registration', 'ege-math-print-2026.pdf', 0),
    ('ege_answers', 'ege-math-print-2026.pdf', 1),
]
reports = []
for name, filename, page_index in cases:
    form = forms[name]
    ege = name.startswith('ege')
    with fitz.open(ASSETS / 'qa' / filename) as doc:
        page = doc[page_index]
        scale = min(3508 / max(page.rect.width, page.rect.height), 4)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = cv2.threshold(gray, 160 if ege else 180, 255, cv2.THRESH_BINARY_INV)[1]
    contours = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    candidates = []
    full = gray.size
    for contour in contours:
        area = cv2.contourArea(contour)
        x, y, w, h = cv2.boundingRect(contour)
        ratio, extent = w / h, area / (w * h)
        keep = (.0002 < area / full < .0015 and .7 < ratio < 1.4 and extent > .75) if ege else (60 < area < 50000 and .66 < ratio < 1.5 and extent > .45)
        if keep:
            candidates.append((x + w / 2, y + h / 2, area))
    source = []
    for index, (mx, my) in enumerate(form['markers']):
        ex, ey = mx / form['size'][0], my / form['size'][1]
        matching = []
        for candidate in candidates:
            x, y = candidate[0] / pix.width, candidate[1] / pix.height
            if ege:
                inside = abs(x - ex) < .065 and abs(y - ey) < (.065 if index < 2 else .055)
                score = (x - ex) ** 2 + (y - ey) ** 2
            else:
                x1, y1, x2, y2 = form['zones'][index]
                inside = x1 <= x <= x2 and y1 <= y <= y2
                score = -candidate[2]
            if inside:
                matching.append((score, candidate))
        assert matching, (name, 'missing marker', index)
        point = min(matching)[1][:2]
        assert point not in source, (name, 'duplicate marker')
        source.append(point)
    assert abs(source[0][1] - source[1][1]) <= pix.height * .045, name
    assert abs(source[2][1] - source[3][1]) <= pix.height * .045, name
    assert source[1][0] - source[0][0] >= pix.width * .5, name
    assert source[2][1] - source[0][1] >= pix.height * .55, name
    matrix = cv2.getPerspectiveTransform(np.float32(source), np.float32(form['markers']))
    aligned = cv2.warpPerspective(image, matrix, tuple(form['size']), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    nonempty = []
    for task, (x1, y1, x2, y2) in form['answers'].items():
        region = cv2.cvtColor(aligned[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        for cell_index in range(17):
            left = int(np.floor(cell_index * region.shape[1] / 17 + .5)) + 5
            right = int(np.floor((cell_index + 1) * region.shape[1] / 17 + .5)) - 5
            cell = region[6:-6, left:right]
            binary = cv2.threshold(cell, 180, 255, cv2.THRESH_BINARY_INV)[1]
            n, _, stats, _ = cv2.connectedComponentsWithStats(binary)
            if any(s[cv2.CC_STAT_AREA] >= 35 and (s[cv2.CC_STAT_WIDTH] >= 10 or s[cv2.CC_STAT_HEIGHT] >= 10) for s in stats[1:]):
                nonempty.append(task)
                break
    thumb = cv2.resize(aligned, (int(aligned.shape[1] * 1000 / aligned.shape[0]), 1000))
    ok, png = cv2.imencode('.png', thumb)
    assert ok
    (OUT / f'{name}.png').write_bytes(png.tobytes())
    reports.append({'layout': name, 'markers_found': 4, 'answer_boxes': len(form['answers']), 'blank_rows_with_ink': nonempty})
(OUT / 'template-report.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(reports, ensure_ascii=False))
