import unittest
from unittest.mock import Mock

import cv2
import numpy as np

from core.grid_reader import assemble, digit_text, inspect_cells, refine_row
from core.math_form import read_row


def row(symbols):
    image = np.full((62, 60 * len(symbols), 3), 255, np.uint8)
    for i, symbol in enumerate(symbols):
        x = i * 60
        if symbol == '#':
            cv2.rectangle(image, (x + 15, 10), (x + 39, 49), (0, 0, 0), -1)
        elif symbol == ',':
            cv2.rectangle(image, (x + 22, 38), (x + 31, 51), (0, 0, 0), -1)
        elif symbol == '-':
            cv2.rectangle(image, (x + 15, 26), (x + 36, 31), (0, 0, 0), -1)
    return image


class GridReaderTests(unittest.TestCase):
    def test_geometry_preserves_sign_order(self):
        cells = inspect_cells(row('-#,##'), 5)
        self.assertEqual([c['symbol'] for c in cells], ['-', None, ',', None, None])
        self.assertEqual(assemble(cells, '068'), '-0,68')
        self.assertIsNone(assemble(cells, '68'))

    def test_single_digit_not_invented_as_sign(self):
        self.assertEqual(inspect_cells(row('#'), 1)[0]['symbol'], None)

    def test_lost_minus_recovered(self):
        result, notes = refine_row(Mock(recognize=Mock(return_value='2')), row('-#'), 2, '2')
        self.assertEqual(result, '-2')
        self.assertTrue(notes)

    def test_lost_digit_and_comma_recovered(self):
        result, notes = refine_row(Mock(recognize=Mock(return_value='195')), row('-#,##'), 5, '-95')
        self.assertEqual(result, '-1,95')
        self.assertTrue(notes)

    def test_existing_between_cell_comma_not_removed(self):
        result, notes = refine_row(Mock(recognize=Mock(return_value='171')), row('###'), 3, '17,1')
        self.assertEqual(result, '17,1')
        self.assertTrue(notes)

    def test_disagreeing_digits_are_not_silently_replaced(self):
        result, notes = refine_row(Mock(recognize=Mock(return_value='723')), row('###'), 3, '123')
        self.assertEqual(result, '123')
        self.assertTrue(notes)

    def test_non_numeric_ocr_is_not_silently_filtered_into_digits(self):
        self.assertEqual(digit_text('1x2'), '')
        self.assertEqual(digit_text('12'), '12')
        result, notes = refine_row(Mock(recognize=Mock(return_value='1x2')), row('##'), 2, '')
        self.assertEqual(result, '')
        self.assertTrue(notes)

    def test_gap_disables_automatic_reassembly(self):
        engine = Mock()
        result, notes = refine_row(engine, row('# #'), 3, '12')
        self.assertEqual(result, '12')
        self.assertTrue(notes)
        engine.recognize.assert_not_called()

    def test_wide_fallback_only_with_same_layout(self):
        engine = Mock(recognize=Mock(side_effect=['4', '48']))
        result, _ = refine_row(engine, row('##'), 2, '2', wider=lambda: row('##'))
        self.assertEqual(result, '48')
        engine = Mock(recognize=Mock(return_value='4'))
        wide = row('##').copy()
        wide[:, :60] = 255
        result, _ = refine_row(engine, row('##'), 2, '2', wider=lambda: wide)
        self.assertEqual(result, '2')
        self.assertEqual(engine.recognize.call_count, 1)

    def test_blank_does_not_call_ocr(self):
        engine = Mock()
        image = row('   ')
        self.assertEqual(read_row(engine, image, (0, 0, 180, 62), 3), ('', []))
        engine.recognize.assert_not_called()

    def test_same_pixels_cannot_depend_on_task_number(self):
        engine = Mock(recognize=Mock(return_value='2'))
        image = row('-#')
        self.assertEqual(read_row(engine, image, (0, 0, 120, 62), 2, task=1),
                         read_row(engine, image, (0, 0, 120, 62), 2, task=19))
