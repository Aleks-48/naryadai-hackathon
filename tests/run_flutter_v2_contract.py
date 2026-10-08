"""Exercise only the final Flutter v2 wire contract against a disposable server copy."""
import base64
import hashlib
import http.client
from http.server import ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import tempfile
import threading
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'server.py'
checks = []

def record(name):
    checks.append(name)
    print('PASS', name, flush=True)

with tempfile.TemporaryDirectory(prefix='enbek-native-contract-') as temp:
    os.environ['NARYADAI_DATA_DIR'] = temp
    for key in ('NARYADAI_LLM_ENABLED', 'NARYADAI_LLM_API_KEY', 'NARYADAI_LLM_MODEL',
                'NARYADAI_LLM_REPORT_SUMMARY', 'NARYADAI_TELEGRAM_ENABLED',
                'NARYADAI_TELEGRAM_BOT_TOKEN', 'NARYADAI_TELEGRAM_WEBHOOK_SECRET'):
        os.environ[key] = ''
    spec = importlib.util.spec_from_file_location('native_contract_server', SERVER)
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    db_path = Path(temp) / 'synthetic.sqlite3'
    app.MEDIA = Path(temp) / 'media'
    app.init_db(db_path)
    app.patch_cookie_login()
    app.patch_get_photo()
    class QuietHandler(app.AppHandler):
        def log_message(self, *_args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
    server.db_path = db_path
    server.daemon_threads = True
    worker_thread = threading.Thread(target=server.serve_forever, daemon=True)
    worker_thread.start()

    class Client:
        def __init__(self): self.cookie = None; self.csrf = None
        def request(self, path, body=None, csrf=True, raw=False):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=25)
            headers = {'Accept':'image/jpeg,image/png,image/webp' if raw else 'application/json', 'Cache-Control':'no-store'}
            if self.cookie: headers['Cookie'] = self.cookie
            if body is not None and csrf and self.csrf: headers['X-CSRF-Token'] = self.csrf
            data = None if body is None else json.dumps(body, ensure_ascii=False, separators=(',',':')).encode('utf-8')
            if data is not None:
                headers['Content-Type'] = 'application/json; charset=utf-8'
                headers['Content-Length'] = str(len(data))
            try:
                connection.request('GET' if body is None else 'POST', path, data, headers)
                response = connection.getresponse()
                content = response.read()
                cookie = response.getheader('Set-Cookie')
                if cookie and cookie.startswith('naryadai_session='): self.cookie = cookie.split(';',1)[0]
                return response.status, content if raw else json.loads(content), response.getheader('Content-Type')
            finally: connection.close()
        def login(self, username):
            status, body, _ = self.request('/api/login', {'username':username, 'password':'demo123'}, csrf=False)
            assert status == 200 and self.cookie and isinstance(body['user']['csrf'],str)
            self.csrf = body['user']['csrf']
            return body['user']

    def image_payload(seed, phase):
        rng = random.Random(seed)
        image = Image.new('RGB',(80,80))
        image.putdata([(rng.randrange(256),rng.randrange(256),rng.randrange(256)) for _ in range(6400)])
        output = io.BytesIO(); image.save(output,format='PNG'); data=output.getvalue()
        return {'phase':phase,'file_name':f'fixture-{seed}.png','data_url':'data:image/png;base64,'+base64.b64encode(data).decode()}, data

    try:
        master, worker, manager, stranger, anonymous = (Client() for _ in range(5))
        master_user=master.login('master01'); worker_user=worker.login('worker01')
        manager.login('manager'); stranger.login('worker15')
        record('login cookie name + user.csrf + UTF-8 fixed-length JSON')
        status, bootstrap, _=master.request('/api/bootstrap')
        assert status==200 and isinstance(bootstrap['orders'],list)
        c=bootstrap['constants']
        for key in ('areas','equipment','users','fault_codes','materials'): assert isinstance(c[key],list) and c[key]
        eq=c['equipment'][0]
        create={'title':'Проверка узла 🔧','description':'Проверить оборудование и записать фактический результат.',
                'issuance_comment':'Синтетическая проверка клиента','work_type':'unscheduled','priority':'normal',
                'area_id':eq['area_id'],'equipment_id':eq['id'],'worker_id':worker_user['id'],'norm_hours':8.0}
        assert master.request('/api/orders',create,csrf=False)[0]==403
        assert worker.request('/api/orders',create)[0]==403
        assert manager.request('/api/orders',create)[0]==403
        record('bootstrap catalogs + missing-CSRF/worker/manager create rejection')
        status, created, _=master.request('/api/orders',create)
        order=created['order']; oid=order['id']
        assert status==201 and order['status']=='issued' and order['photos']==[]
        before,_=image_payload(100,'before')
        status, uploaded, _=master.request(f'/api/orders/{oid}/photos',before)
        assert status==201 and isinstance(uploaded['photo']['id'],int)
        record('native create payload + separate BEFORE photo upload')
        for action in ('accept','start'):
            assert worker.request(f'/api/orders/{oid}/action',{'action':action})[0]==200
        after,after_bytes=image_payload(200,'after')
        status,uploaded,_=worker.request(f'/api/orders/{oid}/photos',after)
        assert status==201
        photo_id=uploaded['photo']['id']
        assert anonymous.request(f'/api/photos/{photo_id}',raw=True)[0]==401
        assert stranger.request(f'/api/photos/{photo_id}',raw=True)[0]==404
        for client in (master,worker,manager):
            status,received,mime=client.request(f'/api/photos/{photo_id}',raw=True)
            assert status==200 and mime=='image/png' and received==after_bytes and len(received)<=4_000_000
        record('protected photo bytes/MIME for allowed roles; anonymous and unrelated worker denied')
        complete={'action':'complete','completion_text':'Выполнена проверка узла; результат описан без утверждения допуска к опасным работам.',
                  'worker_completion_comment':'Тестовый комментарий исполнителя','labor_hours':1.5,
                  'fault_code_id':c['fault_codes'][0]['id'],'materials_not_used':True,'materials':[]}
        status,completed,_=worker.request(f'/api/orders/{oid}/action',complete)
        assert status==200 and completed['order']['status']=='executed'
        status,reviewed,_=worker.request(f'/api/orders/{oid}/action',{'action':'ai_check'})
        assert status==200 and reviewed['order']['status']=='ai_review'
        result=json.loads(reviewed['order']['ai_result'])
        assert result['verdict']=='comments' and result['master_confirmation_required'] is True
        record('worker complete payload + ai_check -> ai_review with mandatory master review')
        status,reworked,_=master.request(f'/api/orders/{oid}/action',{'action':'request_rework','reason':'Нужна повторная проверка.'})
        assert status==200 and reworked['order']['status']=='rework'
        assert not [p for p in reworked['order']['photos'] if p['phase']=='after']
        assert worker.request(f'/api/photos/{photo_id}',raw=True)[0]==404
        assert worker.request(f'/api/orders/{oid}/action',{'action':'start'})[0]==200
        replacement,_=image_payload(300,'after')
        assert worker.request(f'/api/orders/{oid}/photos',replacement)[0]==201
        assert worker.request(f'/api/orders/{oid}/action',complete)[0]==200
        assert worker.request(f'/api/orders/{oid}/action',{'action':'ai_check'})[0]==200
        record('master rework retires previous AFTER images; worker can restart/reupload/report')
        status,closed,_=master.request(f'/api/orders/{oid}/action',{'action':'close','closure_comment':'Мастер проверил отчёт и подтверждает приёмку.','rating':4})
        assert status==200 and closed['order']['status']=='closed' and closed['order']['rating']==4
        assert master.request(f'/api/orders/{oid}/rating',{'rating':5,'reason':'Повторная проверка мастером.'})[0]==200
        assert master.request(f'/api/orders/{oid}')[1]['order']['rating']==5
        record('master close + rating-adjustment payloads')
        status,tg,_=master.request('/api/telegram/status')
        assert status==200 and tg['enabled'] is False and tg['paired'] is False and isinstance(tg['delivery_counts'],dict)
        assert master.request('/api/telegram/pair',{})[0]==409
        assert master.request('/api/telegram/unpair',{})[0]==200
        record('Telegram disabled status/pair rejection/unpair schema; no real binding or token used')
        assert master.request('/api/logout',{})[0]==200
        assert master.request('/api/bootstrap')[0]==401
        record('logout invalidates the session')
    finally:
        server.shutdown();server.server_close();worker_thread.join(timeout=5)
    print(json.dumps({'server_sha256':hashlib.sha256(SERVER.read_bytes()).hexdigest(),'checks':checks,'count':len(checks),'scope':'loopback Python requests matching exact Flutter v2 payloads; not a Dart/device test'},ensure_ascii=False,indent=2))
