"""Optional local Chromium smoke for reporting contracts; synthetic data, no integrations.

Run: python tests/run_pwa_reporting_smoke.py --browser /usr/bin/chromium
Requires the optional playwright Python package and an installed Chromium binary.
Never connects to a deployed app; creates and removes its own temporary database.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', default='/usr/bin/chromium')
    parser.add_argument('--evidence-dir')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='enbekplus-pwa-report-') as directory:
        # Strip inherited integration settings before importing the app. No delivery
        # or watchdog threads run in this smoke. The browser blocks other origins.
        for key in list(os.environ):
            if key.startswith(('NARYADAI_LLM_', 'NARYADAI_TELEGRAM_')):
                os.environ.pop(key)
        os.environ['NARYADAI_LLM_ENABLED'] = '0'
        os.environ['NARYADAI_TELEGRAM_ENABLED'] = '0'
        os.environ['NARYADAI_DATA_DIR'] = directory
        import server as app
        from playwright.sync_api import sync_playwright

        db_path = Path(directory) / 'smoke.sqlite3'
        app.init_db(db_path)
        app.patch_get_photo()
        app.patch_cookie_login()
        http = app.ThreadingHTTPServer(('127.0.0.1', 0), app.AppHandler)
        http.daemon_threads = True
        http.db_path = db_path
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{http.server_port}'
        checks = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=args.browser, headless=True)
                context = browser.new_context(viewport={'width':1440, 'height':1080}, timezone_id='UTC', service_workers='block')
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(origin)
                page.locator('#username').fill('master01')
                page.locator('#password').fill('demo123')
                page.locator('#login-form button[type=submit]').click()
                page.locator('#app').wait_for(state='visible')
                page.locator('[data-view="reports"]').wait_for(state='visible')
                bootstrap = page.request.get(origin+'/api/bootstrap').json()
                order = next(o for o in bootstrap['orders'] if o['status'] in ('issued','accepted','queued','in_progress','paused','rework'))
                page.locator('[data-view="reports"]').click()
                page.locator('#report-from').fill('2001-02-01')
                page.locator('#report-to').fill('2001-02-01')
                page.locator('#report-area').select_option(str(order['area_id']))
                page.locator('#report-equipment').select_option(str(order['equipment_id']))
                page.locator('#report-worker').select_option(str(order['worker']['id']))
                page.locator('#report-brigade').select_option(order['worker']['brigade'])
                page.locator('#report-shift').select_option('A')
                with page.expect_response(lambda r: '/api/reports?' in r.url) as result:
                    page.locator('#load-report').click()
                response = result.value
                assert response.ok, response.text()
                query = parse_qs(urlparse(response.url).query)
                for key,value in [('area_id',order['area_id']),('equipment_id',order['equipment_id']),('worker_id',order['worker']['id'])]:
                    assert query[key] == [str(value)], (key,query)
                assert 'include_ai_summary' not in query
                report = response.json()
                page.locator('#report-result h3', has_text='Текущая загрузка').wait_for()
                assert report['summary']['completed'] == 0
                assert report['summary']['current_active_orders'] > 0
                assert 'Отказы' in page.locator('#report-result').inner_text()
                assert 'без фильтра дат/смены' in page.locator('#report-result').inner_text()
                checks.append('All report query filters; no implicit AI; empty event period still shows current workload')

                page.locator('#downtime-equipment').select_option(str(order['equipment_id']))
                page.locator('#downtime-order').select_option(str(order['id']))
                page.locator('#downtime-start').fill('2001-02-01T06:30')
                page.locator('#downtime-end').fill('2001-02-01T07:30')
                page.locator('#downtime-reason').fill('Synthetic UI contract smoke')
                with page.expect_response(lambda r: '/api/equipment/downtime' in r.url and r.request.method=='POST') as saved:
                    with page.expect_response(lambda r: '/api/reports?' in r.url) as after:
                        page.locator('#downtime-submit').click()
                assert saved.value.status == 201, saved.value.text()
                assert saved.value.request.post_data_json['order_id'] == order['id']
                assert saved.value.json()['item']['order_id'] == order['id']
                assert after.value.json()['summary']['equipment_downtime_minutes'] == 60
                page.get_by_text('Зарегистрированный простой оборудования: 60 мин', exact=True).wait_for()
                checks.append('Optional downtime order_id survives real POST and worker/brigade-filtered report shows 60 minutes')

                page.locator('[data-view="home"]').click()
                page.locator('[data-view="reports"]').click()
                for control,value in [('report-area',order['area_id']),('report-equipment',order['equipment_id']),('report-worker',order['worker']['id'])]:
                    assert page.locator('#'+control).input_value()==str(value)
                assert 'Текущая загрузка' in page.locator('#report-result').inner_text()
                if args.evidence_dir:
                    evidence=Path(args.evidence_dir);evidence.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(evidence/'pwa-reports-desktop.png'),full_page=True)
                other_area=next(a for a in bootstrap['constants']['areas'] if a['id']!=order['area_id'])
                page.locator('#report-area').select_option(str(other_area['id']))
                assert page.locator('#report-equipment').input_value()==''
                assert page.locator(f'#report-equipment option[value="{order["equipment_id"]}"]').count()==0
                checks.append('Submitted report filters and results survive navigation; incompatible equipment clears on area change')

                page.locator('[data-view="team"]').click()
                roster_count=page.locator('.team-person').count()
                page.locator('#team-shift-filter').select_option('C')
                with page.expect_response(lambda r: '/api/bootstrap?' in r.url and 'rating_shift=C' in r.url) as rating:
                    page.locator('#apply-team-filters').click()
                assert 'shift_code' not in parse_qs(urlparse(rating.value.url).query)
                page.wait_for_function('(count) => document.querySelectorAll(".team-person").length === count', arg=roster_count)
                checks.append('Rating shift uses rating_shift and does not remove other roster shifts')

                page.locator('[data-view="reports"]').click()
                page.set_viewport_size({'width':390,'height':844})
                assert page.locator('#report-area').is_visible()
                assert page.locator('#report-equipment').is_visible()
                assert page.locator('#report-worker').is_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                if args.evidence_dir:
                    page.screenshot(path=str(Path(args.evidence_dir)/'pwa-reports-mobile.png'),full_page=True)
                checks.append('390 px viewport has usable report controls and no document-level horizontal overflow')
                assert not errors, errors
                result={'checks':checks,'browser':browser.version,'page_errors':errors,'external_integrations':'disabled; external browser origins blocked'}
                print(json.dumps(result,ensure_ascii=False,indent=2))
                if args.evidence_dir:
                    (Path(args.evidence_dir)/'pwa-report-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
                browser.close()
        finally:
            http.shutdown()
            http.server_close()
            thread.join(timeout=5)


if __name__=='__main__':
    main()
