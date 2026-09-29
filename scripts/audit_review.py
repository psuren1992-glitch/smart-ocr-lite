"""Read-only audit of teacher edits. Agreement is NOT measured OCR accuracy."""
import argparse
from collections import Counter
import json
from pathlib import Path


def audit(folder):
    meta = json.loads((folder / 'work.json').read_text(encoding='utf-8'))
    counts = Counter()
    changes = []
    correction_pages = []
    by_task = Counter()
    for number in range(1, meta['count'] + 1):
        path = folder / str(number) / 'page.json'
        if not path.exists():
            counts['missing_pages'] += 1
            continue
        page = json.loads(path.read_text(encoding='utf-8'))
        if not page.get('reviewed'):
            counts['unreviewed_pages'] += 1
            continue
        counts['reviewed_pages'] += 1
        if page.get('corrections'):
            correction_pages.append(number)
        for task in map(str, range(1, 20)):
            raw = page.get('raw', {})
            answers = page.get('answers', {})
            if task not in raw or task not in answers:
                counts['missing_fields'] += 1
                continue
            before, after = raw[task], answers[task]
            counts['compared_fields'] += 1
            counts['filled_final_fields'] += bool(after)
            if before == after:
                counts['unchanged_fields'] += 1
                counts['unchanged_filled_fields'] += bool(after)
                continue
            counts['changed_fields'] += 1
            by_task[task] += 1
            kind = 'changed_text'
            if not before:
                kind = 'filled_after_blank'
            elif not after:
                kind = 'cleared'
            elif before.translate(str.maketrans('', '', '-,.')) == after.translate(str.maketrans('', '', '-,.')):
                kind = 'punctuation_only'
            counts[kind] += 1
            changes.append({'page': number, 'task': task, 'raw': before,
                            'final': after, 'kind': kind})
    return {
        'warning': 'Edit agreement only, not OCR accuracy. Final answers may include replacements. '
                   'Unchanged fields can still be wrong. Correction OCR can miss populated blocks. '
                   'Do not use final answers as crop labels without source verification.',
        'expected_pages': meta['count'], 'counts': dict(counts),
        'pages_with_detected_corrections': correction_pages,
        'changes_by_task': dict(by_task.most_common()), 'changes': changes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work_folder', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.work_folder), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
