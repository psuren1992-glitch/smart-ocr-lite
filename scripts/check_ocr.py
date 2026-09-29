"""Compare saved raw OCR with an independently transcribed reference, not answer keys."""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work_folder',type=Path)
    args=parser.parse_args()
    reference=json.loads((Path(__file__).resolve().parents[1]/'tests/ocr_reference.json').read_text(encoding='utf-8'))
    total=correct=filled=filled_correct=0
    failures=[]
    for number, expected in reference['pages'].items():
        path=args.work_folder/number/'page.json'
        if not path.exists():
            raise SystemExit(f'Missing page {number}: {path}')
        actual=json.loads(path.read_text(encoding='utf-8'))
        if actual.get('status') != 'ready':
            raise SystemExit(f'Page {number} is not ready')
        for task, value in expected['answers'].items():
            total+=1
            got=actual['raw'].get(task)
            match=got==value
            correct+=match
            filled+=bool(value)
            filled_correct+=bool(value) and match
            if not match:
                failures.append(f'page={number} task={task}: expected={value!r}, got={got!r}')
        if actual['corrections'] != expected['corrections']:
            failures.append(f'page={number}: corrections differ')
    print(f'Exact fields: {correct}/{total}; nonempty: {filled_correct}/{filled}')
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__=='__main__':
    raise SystemExit(main())
