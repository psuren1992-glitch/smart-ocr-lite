import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_review import audit


class AuditTests(unittest.TestCase):
    def test_counts_and_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'work.json').write_text(json.dumps({'count': 3}))
            (root / '1').mkdir()
            (root / '2').mkdir()
            raw = {str(t): '' for t in range(1, 20)}
            raw.update({'1': '171', '2': '2', '4': '9'})
            answers = dict(raw, **{'1': '17,1', '2': '3', '3': '5', '4': ''})
            path = root / '1/page.json'
            path.write_text(json.dumps({'reviewed': True, 'raw': raw,
                                        'answers': answers, 'corrections': [{'task': '2', 'answer': '3'}]}))
            original = path.read_bytes()
            (root / '2/page.json').write_text(json.dumps({'reviewed': False}))
            result = audit(root)
            self.assertEqual(result['counts']['compared_fields'], 19)
            self.assertEqual(result['counts']['changed_fields'], 4)
            self.assertEqual(result['counts']['punctuation_only'], 1)
            self.assertEqual(result['counts']['missing_pages'], 1)
            self.assertEqual(result['counts']['unreviewed_pages'], 1)
            self.assertEqual(result['pages_with_detected_corrections'], [1])
            self.assertEqual(path.read_bytes(), original)

    def test_missing_raw_is_not_a_blank_prediction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'work.json').write_text(json.dumps({'count': 1}))
            (root / '1').mkdir()
            (root / '1/page.json').write_text(json.dumps({'reviewed': True, 'answers': {'1': '2'}}))
            result = audit(root)
            self.assertEqual(result['counts']['missing_fields'], 19)
            self.assertEqual(result['changes'], [])
