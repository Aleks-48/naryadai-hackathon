"""Read-only source import; exercise existing API against temporary synthetic data.
Usage: python tool/check_create_contract.py /path/to/server.py
Requires backend Pillow dependency. No public server, real account, token or DB.
"""
import base64
from datetime import datetime, timedelta, timezone
import http.client
from http.server import ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from PIL import Image, ImageDraw


def main():
    with tempfile.TemporaryDirectory(prefix='enbek-create-contract-') as temp:
        os.environ['NARYADAI_DATA_DIR'] = temp
        spec = importlib.util.spec_from_file_location('create_contract_backend', Path(sys.argv[1]).resolve())
        app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app)
        app.MEDIA = Path(temp) / 'media'
        database = Path(temp) / 'synthetic.sqlite3'
        app.init_db(database)
        app.patch_cookie_login()
        class QuietHandler(app.AppHandler):
            def log_message(self, *_args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        server.db_path = database
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def call(path, body=None, auth=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            headers = {'Accept': 'application/json'}
            if auth:
                headers['Cookie'], headers['X-CSRF-Token'] = auth
            raw = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
            if raw is not None: headers['Content-Type'] = 'application/json'
            try:
                connection.request('GET' if body is None else 'POST', path, raw, headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read()), response.getheader('Set-Cookie')
            finally:
                connection.close()
        def login(username):
            status, body, cookie = call('/api/login', {'username': username, 'password': 'demo123'})
            assert status == 200
            return cookie.split(';', 1)[0], body['user']['csrf']
        try:
            master, worker, manager = (login(name) for name in ('master01', 'worker01', 'manager'))
            _, bootstrap, _ = call('/api/bootstrap', auth=master)
            equipment = bootstrap['constants']['equipment'][0]
            worker_id = next(p['id'] for p in bootstrap['constants']['users'] if p['role'] == 'worker')
            payload = {'title': 'Проверка узла 🔧', 'description': 'Проверить узел и записать результат проверки.',
                'issuance_comment': 'Тестовая выдача', 'work_type': 'unscheduled', 'priority': 'normal',
                'area_id': equipment['area_id'], 'equipment_id': equipment['id'], 'worker_id': worker_id, 'norm_hours': 8}
            for denied in (worker, manager):
                assert call('/api/orders', payload, denied)[0] == 403
            print('PASS only master can create; worker and manager denied')
            for priority in ('planned', 'normal', 'high', 'emergency'):
                status, body, _ = call('/api/orders', {**payload, 'priority': priority}, master)
                assert status == 201 and body['order']['priority'] == priority
            order = body['order']
            assert order['photos'] == [] and order['status'] == 'issued'
            print('PASS all four priorities and photo-optional creation')
            brigade_payload = {k: v for k, v in payload.items() if k not in ('worker_id', 'norm_hours')}
            deadline = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
            status, body, _ = call('/api/orders', {**brigade_payload, 'brigade': 'A', 'work_type': 'planned', 'due_at': deadline}, master)
            assert status == 201 and body['order']['work_type'] == 'planned'
            assert body['order']['assigned_brigade'] == 'A'
            print('PASS brigade assignment and future UTC deadline')
            assert call('/api/orders', {**payload, 'brigade': 'A'}, master)[0] == 400
            assert call('/api/orders', {**payload, 'norm_hours': 0}, master)[0] == 400
            assert call('/api/orders', {**payload, 'due_at': '2000-01-01T00:00:00Z'}, master)[0] == 400
            print('PASS dual assignee, zero hours and past deadline rejected')
            for index in range(5):
                image = Image.new('RGB', (128,128), (30+index*30,90+index*20,170-index*25))
                draw = ImageDraw.Draw(image)
                draw.rectangle((index*8,16,70+index*5,75),fill=(220,20+index*20,80))
                buffer=io.BytesIO();image.save(buffer,format='PNG')
                photo = {'phase':'before','file_name':f'create-fixture-{index}.png',
                    'data_url':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()}
                assert call(f"/api/orders/{order['id']}/photos", photo, master)[0] == 201
            assert call(f"/api/orders/{order['id']}/photos", photo, master)[0] == 400
            _, detail, _ = call(f"/api/orders/{order['id']}", auth=master)
            assert len([p for p in detail['order']['photos'] if p['phase']=='before']) == 5
            print('PASS create-once then five BEFORE uploads; sixth rejected; same order retained')
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

if __name__ == '__main__': main()
