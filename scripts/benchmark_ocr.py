"""Evaluate frozen, locally reviewed labels without overwriting any work data."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.math_form import answer_boxes, classifier, form_config, read_row, OCR_VERSION


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work_folder', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.work_folder.resolve()) or args.output.exists():
        parser.error('Use a new output file outside the source work')
    reference = json.loads(args.reference.read_text(encoding='utf-8'))
    meta = json.loads((args.work_folder / 'work.json').read_text(encoding='utf-8'))
    if len(reference['pages']) != meta['count']:
        parser.error('Reference page count does not match work')
    watched = {args.work_folder / number / name: digest
               for number, p in reference['pages'].items() for name, digest in p['hashes'].items()}
    for path, digest in watched.items():
        if sha256(path) != digest:
            parser.error(f'Source changed since reference was frozen: {path}')
    start = time.perf_counter()
    engine = classifier()
    counts = Counter()
    rows, corrections = [], []
    cfg = form_config()
    for number, page in reference['pages'].items():
        scan = cv2.imdecode(np.fromfile(args.work_folder / number / 'scan.png', np.uint8), 1)
        if scan is None:
            raise ValueError(f'Cannot read scan {number}')
        for task, box in answer_boxes().items():
            actual, notes = read_row(engine, scan, box, 17)
            expected, baseline = page['answers'][task], page['raw'][task]
            excluded = page.get('excluded', {}).get(task)
            if not excluded:
                counts['total'] += 1
                counts['baseline_correct'] += baseline == expected
                counts['candidate_correct'] += actual == expected
                counts['filled'] += bool(expected)
                counts['baseline_filled_correct'] += bool(expected) and baseline == expected
                counts['candidate_filled_correct'] += bool(expected) and actual == expected
                counts['improved'] += baseline != expected and actual == expected
                counts['regressions'] += baseline == expected and actual != expected
                counts['flagged'] += bool(notes)
            else:
                counts['excluded'] += 1
            rows.append({'page': int(number), 'task': task, 'expected': expected, 'baseline': baseline,
                         'candidate': actual, 'excluded': excluded, 'notes': notes})
        detected = []
        for block in cfg['corrections']:
            for y in block['centers']:
                task, _ = read_row(engine, scan, [block['task_x1'], y-28, block['task_x2'], y+28], 2)
                answer, _ = read_row(engine, scan, [block['answer_x1'], y-28, block['answer_x2'], y+28], 17)
                if task or answer:
                    detected.append({'task': task, 'answer': answer})
        corrections.append({'page': int(number), 'candidate': detected,
                            'expected': page['corrections'], 'baseline': page['raw_corrections']})
        print(f'Page {number} evaluated', flush=True)
    for path, digest in watched.items():
        if sha256(path) != digest:
            raise RuntimeError(f'Source changed during evaluation: {path}')
    report = {'ocr_version': OCR_VERSION, 'reference_sha256': sha256(args.reference),
              'config_sha256': sha256(Path(__file__).resolve().parents[1] / 'config/math_2026_2027.json'),
              'warning': 'Development sample, not independent validation. No answer keys used.',
              'seconds': round(time.perf_counter() - start, 2), 'source_unchanged': True,
              'counts': dict(counts), 'rows': rows, 'corrections': corrections}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report['counts'], indent=2))
    return int(counts['regressions'] > 0)


if __name__ == '__main__':
    raise SystemExit(main())
