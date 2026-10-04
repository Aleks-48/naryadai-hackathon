"""Independent synthetic-data regressions from source review, 2026-10-02."""
import json
import unittest
import unittest.mock
from datetime import timedelta
import tests.test_app as fixture
import server as app


class IndependentSecurityQA(unittest.TestCase):
    setUpClass = classmethod(fixture.LocalAPITest.setUpClass.__func__)
    tearDownClass = classmethod(fixture.LocalAPITest.tearDownClass.__func__)
    client = fixture.LocalAPITest.client
    create_order = fixture.LocalAPITest.create_order
    action = fixture.LocalAPITest.action
    upload = fixture.LocalAPITest.upload
    close_planned_order = fixture.LocalAPITest.close_planned_order

    def test_previous_executor_cannot_mutate_reassigned_order(self):
        master = self.client('master01'); old = self.client('worker01'); new = self.client('worker02')
        oid = self.create_order(master)['id']
        self.assertEqual(self.action(old, oid, 'reject', reason='Нет материалов для ремонта')[0], 200)
        new_id = new.call('/api/me')[1]['user']['id']
        self.assertEqual(master.call(f'/api/orders/{oid}/assign', 'POST', {'worker_id': new_id})[0], 200)
        self.assertEqual(old.call(f'/api/orders/{oid}')[0], 200) # Historical read remains allowed.
        self.assertEqual(self.action(old, oid, 'accept')[0], 403)
        self.assertEqual(self.action(new, oid, 'accept')[0], 200)
        self.assertEqual(self.action(new, oid, 'start')[0], 200)
        self.assertEqual(self.action(old, oid, 'pause', reason='Недопустимое действие старого исполнителя')[0], 403)

    def test_disabled_account_existing_session_is_revoked(self):
        worker = self.client('worker15')
        with app.connect(self.db_path) as db:
            db.execute('UPDATE users SET is_active=0 WHERE id=?', (self.worker15_id,))
        try:
            self.assertEqual(worker.call('/api/me')[0], 401)
        finally:
            with app.connect(self.db_path) as db:
                db.execute('UPDATE users SET is_active=1 WHERE id=?', (self.worker15_id,))

    def test_timezone_less_deadline_and_nonfinite_numbers_are_client_errors(self):
        master = self.client('master01')
        payload = {'title':'Проверка числовых полей','description':'Проверить ввод даты и положительных конечных чисел.',
                   'work_type':'planned','priority':'normal','area_id':self.area_id,'equipment_id':self.equipment_id,
                   'worker_id':self.worker_id,'norm_hours':8}
        for changes in ({'due_at':'2030-10-02T12:00'}, {'norm_hours':'nan'}, {'norm_hours':'inf'}):
            with self.subTest(changes=changes):
                self.assertEqual(master.call('/api/orders', 'POST', {**payload, **changes})[0], 400)
        worker = self.client('worker01'); oid = self.create_order(master)['id']
        self.action(worker, oid, 'accept'); self.action(worker, oid, 'start')
        completion = {'completion_text':'Выполнена проверка крепления, результат стабилен.',
                      'fault_code_id':self.fault_id,'labor_hours':'nan','materials':[],'materials_not_used':True}
        self.assertEqual(self.action(worker, oid, 'complete', **completion)[0], 400)

    def test_duplicate_material_lines_return_validation_error(self):
        master = self.client('master01'); worker = self.client('worker01'); oid = self.create_order(master)['id']
        self.action(worker,oid,'accept'); self.action(worker,oid,'start')
        materials=[{'material_id':1,'quantity':1},{'material_id':1,'quantity':2}]
        result=self.action(worker,oid,'complete',completion_text='Выполнена проверка крепления, результат стабилен.',
                           fault_code_id=self.fault_id,labor_hours=1,materials=materials)
        self.assertEqual(result[0],400)
        self.assertEqual(worker.call(f'/api/orders/{oid}')[1]['order']['status'],'in_progress')

    def test_before_photo_capacity_preserves_after_photo_capacity(self):
        master = self.client('master01'); worker = self.client('worker01'); oid = self.create_order(master)['id']
        for index in range(5):
            raw=fixture.make_photo(background=(20+index*30,15,40))
            body={'phase':'before','file_name':f'before-{index}.png',
                  'data_url':'data:image/png;base64,'+fixture.base64.b64encode(raw).decode()}
            self.assertEqual(master.call(f'/api/orders/{oid}/photos','POST',body)[0],201)
        self.action(worker,oid,'accept'); self.action(worker,oid,'start')
        self.assertEqual(self.upload(worker,oid,fixture.make_photo(background=(10,230,70)))[0],201)

    def test_stale_exif_requires_explicit_master_review(self):
        metadata=app.inspect_image(fixture.make_photo('JPEG',capture_time='2000:01:01 00:00:00',offset='+00:00'),'image/jpeg')
        photo={'duplicate':0,'duplicate_type':'none','metadata_json':json.dumps(metadata),'uploaded_at':app.iso()}
        context={'completed_at':app.iso()}
        result=app.complete_review('Выполнена проверка крепления и очистка; результат стабилен.',[photo],1,1.0,'unscheduled',context)
        self.assertEqual(result['verdict'],'comments')
        self.assertTrue(result['master_confirmation_required'])
        self.assertTrue(any('съём' in issue.lower() or 'exif' in issue.lower() for issue in result['issues']))

    def test_ai_generated_rework_is_in_rating_evidence(self):
        master=self.client('master01');worker=self.client('worker01')
        oid=self.close_planned_order(master,worker)
        with app.connect(self.db_path) as db:
            before=app.worker_rating(db,self.worker_id)['evidence']['rework_orders']
            app.audit(db,self.worker_id,oid,'ai_check',{'verdict':'rework'})
            after=app.worker_rating(db,self.worker_id)['evidence']['rework_orders']
        self.assertEqual(after,before+1)

    def test_reissued_order_gets_fresh_acceptance_escalation(self):
        master=self.client('master01');worker=self.client('worker01');oid=self.create_order(master)['id']
        stale=app.iso(app.utcnow()-timedelta(minutes=12))
        with app.connect(self.db_path) as db:
            db.execute('UPDATE orders SET issued_at=? WHERE id=?',(stale,oid));app.maybe_escalate(db)
        self.action(worker,oid,'reject',reason='Не хватает материала для работы')
        self.action(master,oid,'reissue')
        with app.connect(self.db_path) as db:
            # The new acceptance window passes without acknowledgement.
            db.execute('UPDATE orders SET issued_at=? WHERE id=?',(stale,oid));app.maybe_escalate(db)
            total=db.execute("SELECT COUNT(*) FROM audit WHERE order_id=? AND event='acceptance_escalated'",(oid,)).fetchone()[0]
        self.assertEqual(total,2)

    def test_notification_read_state_reaches_bootstrap(self):
        master=self.client('master01');worker=self.client('worker01');oid=self.create_order(master)['id']
        before=worker.call('/api/bootstrap')[1]['notifications']
        self.assertTrue(any(n['order_id']==oid and not n.get('read_at') for n in before))
        self.assertEqual(worker.call('/api/notifications/read','POST',{})[0],200)
        after=worker.call('/api/bootstrap')[1]['notifications']
        self.assertTrue(all(n.get('read_at') for n in after))

    def test_parallel_timer_sweeps_preserve_single_notifications(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        master=self.client('master01');oid=self.create_order(master)['id']
        with app.connect(self.db_path) as db:
            db.execute('UPDATE orders SET issued_at=?,due_at=? WHERE id=?',
                       (app.iso(app.utcnow()-timedelta(minutes=15)),app.iso(app.utcnow()-timedelta(minutes=5)),oid))
        barrier=threading.Barrier(6)
        def sweep(_):
            barrier.wait(timeout=5)
            with app.connect(self.db_path) as db: app.maybe_escalate(db)
        with ThreadPoolExecutor(max_workers=6) as pool: list(pool.map(sweep,range(6)))
        with app.connect(self.db_path) as db:
            for event in ('acceptance_escalated','deadline_escalated'):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM audit WHERE order_id=? AND event=?',(oid,event)).fetchone()[0],1)

    def test_photo_capture_dates_are_uncertain_without_timezone_or_outside_window(self):
        for captured,offset in [('2000:01:01 00:00:00','+00:00'),('2099:01:01 00:00:00','+00:00'),
                                (app.utcnow().strftime('%Y:%m:%d %H:%M:%S'),None)]:
            with self.subTest(captured=captured,offset=offset):
                metadata=app.inspect_image(fixture.make_photo('JPEG',capture_time=captured,offset=offset),'image/jpeg')
                photo={'duplicate':0,'duplicate_type':'none','metadata_json':json.dumps(metadata),'uploaded_at':app.iso()}
                result=app.complete_review('Выполнена проверка крепления и очистка; результат стабилен.',[photo],1,1,'unscheduled',{'completed_at':app.iso()})
                self.assertEqual(result['verdict'],'comments');self.assertTrue(result['master_confirmation_required'])

    def test_untrusted_model_shapes_fail_closed_to_labelled_rules(self):
        import io
        import os
        shapes=[{'choices':[]},{'choices':[{'message':{'content':json.dumps({'summary':[], 'issues':[]})}}]},
                {'choices':[{'message':{'content':json.dumps({'summary':'ok', 'issues':[{'bad':'shape'}]})}}]}]
        env={'NARYADAI_LLM_ENABLED':'1','NARYADAI_LLM_API_URL':app.GEMINI_OPENAI_ENDPOINT,
             'NARYADAI_LLM_API_KEY':'synthetic-test-only','NARYADAI_LLM_MODEL':'synthetic'}
        for shape in shapes:
            opener=unittest.mock.Mock()
            opener.open.return_value=io.BytesIO(json.dumps(shape).encode())
            with self.subTest(shape=shape), unittest.mock.patch.dict(os.environ,env), unittest.mock.patch.object(app.urllib.request,'build_opener',return_value=opener):
                result=app.llm_review('Выполнена проверка, результат стабилен.')
                self.assertEqual(result['mode'],'rules-only: adapter_error')

    def test_static_traversal_and_logout_are_denied(self):
        worker=self.client('worker01')
        for path in ('/static/../server.py','/static/%2e%2e/server.py','/static/%2fetc/passwd'):
            self.assertEqual(worker.call_bytes(path)[0],404)
        self.assertEqual(worker.call('/api/logout','POST',{})[0],200)
        self.assertEqual(worker.call('/api/me')[0],401)

    def test_repeat_on_later_repair_does_not_penalize_later_worker(self):
        master=self.client('master01');worker=self.client('worker01')
        oid=self.close_planned_order(master,worker)
        with app.connect(self.db_path) as db:
            other=db.execute("SELECT id FROM users WHERE username='worker02'").fetchone()[0]
            db.execute('UPDATE orders SET assigned_to=?,repeat_confirmed=1 WHERE id=?',(other,oid))
            detail=app.worker_rating(db,other)
        self.assertEqual(detail['factors']['rework_repeat'],100.0)
        self.assertEqual(detail['evidence']['unattributed_repeat_failures'],1)
        self.assertEqual(detail['evidence']['repeat_penalty_status'],'explicit_master_link_only')
