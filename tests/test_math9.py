import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import numpy as np
import cv2

from core.math_form import clean_grid, answer_boxes, align_form, form_config
from webapp import create_app, grade, read_json, write_json, run_work


class Math9Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.app.testing = True
        self.client = self.app.test_client()
        accounts = self.app.extensions['accounts']
        admin = accounts.register((self.root / '_access/setup-code.txt').read_text(),
                                  'admin', 'test-password-long', 'Test Admin', setup=True)
        with self.client.session_transaction() as s:
            s['user_id'], s['version'] = admin['id'], admin['session_version']
        self.client.get('/')
        with self.client.session_transaction() as s:
            self.csrf = s['csrf']

    def make_work(self):
        wid = 'a'*32
        folder = self.root/wid
        (folder/'1').mkdir(parents=True)
        write_json(folder/'work.json', {'id':wid,'title':'Test','class_name':'9B','count':1,'created':'2026-09-26','finished':True})
        write_json(folder/'keys.json', {})
        write_json(folder/'1/page.json', {'number':1,'status':'ready','name':'Example','variant':'1',
                   'answers':{'1':'0.5'},'raw':{'1':'0.5'},'notes':{},'corrections':[],'reviewed':False})
        return folder, '/work/'+wid

    def test_score_requires_review_and_key(self):
        p = {'answers':{'1':'0.5'},'variant':'1','reviewed':False}
        self.assertIsNone(grade(p,{'1':{'1':'0,5'}}))
        p['reviewed'] = True
        self.assertIsNone(grade(p,{}))
        self.assertEqual(grade(p,{'1':{'1':'0,5|1/2'}}),{'correct':1,'total':1})

    def test_variant_is_exact_and_empty_is_not_correct(self):
        p = {'answers':{'1':'','2':'12'},'variant':'1','reviewed':True}
        self.assertIsNone(grade(p,{'10':{'2':'12'}}))
        self.assertEqual(grade(p,{'1':{'1':'','2':'12'}}),{'correct':1,'total':1})

    def test_grid_removes_dots_but_keeps_minus(self):
        image=np.full((62,180,3),255,np.uint8)
        for x in range(0,180,5):
            cv2.circle(image,(x,8),1,(0,0,0),-1)
            cv2.circle(image,(x,53),1,(0,0,0),-1)
        _,last=clean_grid(image,(0,0,180,62),3)
        self.assertEqual(last,-1)
        cv2.line(image,(18,30),(40,30),(0,0,0),4)
        _,last=clean_grid(image,(0,0,180,62),3)
        self.assertEqual(last,0)

    def test_requires_four_markers(self):
        with self.assertRaises(ValueError):
            align_form(np.full((1000,700,3),255,np.uint8))

    def test_template_has_exactly_19_valid_boxes(self):
        boxes=answer_boxes(); w,h=form_config()['page_size']
        self.assertEqual(set(boxes),{str(i) for i in range(1,20)})
        for x1,y1,x2,y2 in boxes.values():
            self.assertTrue(0<=x1<x2<=w and 0<=y1<y2<=h)

    def test_pages_render_and_unknown_work_is_404(self):
        _,url=self.make_work()
        for path in ['/',url,url+'/page/1',url+'/key']:
            self.assertEqual(self.client.get(path).status_code,200,path)
        self.assertEqual(self.client.get('/work/no-such-work').status_code,404)

    def test_save_preserves_raw_and_needs_correction_confirmation(self):
        folder,url=self.make_work()
        form={'csrf':self.csrf,'action':'verify','answer_1':'1/2','name':'Checked','variant':'2'}
        self.client.post(url+'/page/1',data=form)
        self.assertFalse(read_json(folder/'1/page.json')['reviewed'])
        form['checked_corrections']='yes'
        self.client.post(url+'/page/1',data=form)
        p=read_json(folder/'1/page.json')
        self.assertTrue(p['reviewed']); self.assertEqual(p['raw']['1'],'0.5')
        self.assertEqual(p['answers']['1'],'1/2'); self.assertEqual(p['variant'],'2')
        form['action']='draft'; self.client.post(url+'/page/1',data=form)
        self.assertFalse(read_json(folder/'1/page.json')['reviewed'])

    def test_csrf_rejects_missing_and_unicode_tokens(self):
        _,url=self.make_work()
        for token in ['', 'неверный']:
            self.assertEqual(self.client.post(url+'/page/1',data={'csrf':token}).status_code,400)

    def test_invalid_upload_does_not_create_work(self):
        self.client.post('/upload',data={'csrf':self.csrf,'pdf':(io.BytesIO(b'not pdf'),'bad.pdf')})
        self.assertEqual(list(self.root.glob('*/work.json')),[])

    def test_exam_subject_profiles_saved_without_wrong_ocr(self):
        with fitz.open() as doc:
            doc.new_page()
            content = doc.tobytes()
        for exam, subject in [('oge', 'math'), ('oge', 'russian'), ('ege', 'math'), ('ege', 'russian')]:
            supported = exam == 'oge' and subject == 'math'
            with self.subTest(exam=exam, subject=subject), patch('webapp.enqueue') as queued:
                result = self.client.post('/upload', data={'csrf': self.csrf, 'exam': exam, 'subject': subject,
                    'pdf': (io.BytesIO(content), 'profile.pdf')})
                self.assertEqual(result.status_code, 302)
                self.assertEqual(queued.call_count, int(supported))
                folder = self.root / result.location.rsplit('/', 1)[-1]
                meta = read_json(folder / 'work.json')
                self.assertEqual((meta['exam'], meta['subject']), (exam, subject))
                self.assertEqual(bool(meta['template']), supported)
                response = self.client.get(result.location)
                self.assertEqual(response.status_code, 200)
                if not supported:
                    self.assertIn('Ожидает настройки шаблона', response.data.decode())
                    for suffix in ['/key', '/export']:
                        self.assertEqual(self.client.get(result.location + suffix).status_code, 409)
                    self.assertEqual(self.client.post(result.location + '/resume', data={'csrf': self.csrf}).status_code, 409)
                    with patch('webapp.recognize_page') as recognize:
                        run_work(folder)
                        recognize.assert_not_called()
                    self.assertFalse((folder / '1').exists())

    def test_invalid_profile_rejected_and_legacy_unchanged(self):
        self.assertEqual(self.client.post('/upload', data={'csrf': self.csrf, 'exam': 'bad'}).status_code, 400)
        folder, url = self.make_work()
        before = (folder / 'work.json').read_bytes()
        self.assertIn('ОГЭ · Математика', self.client.get(url).data.decode())
        self.assertEqual((folder / 'work.json').read_bytes(), before)
        home = self.client.get('/').data.decode()
        self.assertIn('name="exam"', home)
        self.assertIn('name="subject"', home)
        self.assertIn('brand.svg', home)
        self.assertIn('Бланки · Проверка работ', home)

    def test_upload_queues_valid_pdf(self):
        with fitz.open() as doc:
            doc.new_page()
            data=doc.tobytes()
        with patch('webapp.enqueue') as queued:
            r=self.client.post('/upload',data={'csrf':self.csrf,'pdf':(io.BytesIO(data),'scan.pdf')})
        self.assertEqual(r.status_code,302); queued.assert_called_once()
        folder=queued.call_args.args[0]
        self.assertEqual(read_json(folder/'work.json')['count'],1)
        self.assertEqual(read_json(folder/'keys.json'),{})

    def test_page_error_does_not_abort_batch(self):
        folder,url=self.make_work()
        meta=read_json(folder/'work.json'); meta['count']=3; write_json(folder/'work.json',meta)
        with fitz.open() as doc:
            for _ in range(3): doc.new_page()
            doc.save(folder/'source.pdf')
        with patch('webapp.recognize_page',side_effect=[ValueError('bad scan'),{'status':'ready','reviewed':False}]) as ocr:
            run_work(folder)
        self.assertEqual(ocr.call_count,2)
        self.assertEqual(read_json(folder/'1/page.json')['raw'],{'1':'0.5'})
        self.assertEqual(read_json(folder/'2/page.json')['status'],'error')
        self.assertEqual(read_json(folder/'3/page.json')['status'],'ready')

    def test_export_has_status_and_protects_formula_cells(self):
        folder,url=self.make_work()
        p=read_json(folder/'1/page.json'); p['name']='=1+1'; write_json(folder/'1/page.json',p)
        data=self.client.get(url+'/export').data.decode('utf-8-sig')
        self.assertIn("'=1+1",data)
        self.assertIn('Не проверен',data)


if __name__=='__main__':
    unittest.main()
