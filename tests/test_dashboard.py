"""Cross-process native/service behavior: widgets, reminders, and offline calendar."""
import ctypes
from contextlib import contextmanager
import hashlib
from datetime import datetime
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.apps = self.directory / 'apps'
        self.state = self.directory / 'run/state.tsv'
        self.channel = self.directory / 'run/services.sock'
        self.binary = ROOT / 'build/host/paperos'
        for package in ('alarm', 'calendar', 'weather', 'mihome'):
            subprocess.run([str(self.binary), '--app-root', str(self.apps), '--install', str(ROOT / 'examples' / (package + '.papp'))],
                           check=True, capture_output=True)
        self.service = subprocess.Popen([str(ROOT / 'build/host/paperos-services'), '--simulate',
                                         '--root', str(self.directory / 'data'), '--run-dir', str(self.directory / 'run')],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            if self.channel.exists() and self.state.exists():
                break
            if self.service.poll() is not None:
                self.fail('service exited before opening its control channel')
            time.sleep(.025)

    def tearDown(self):
        self.service.terminate()
        self.service.wait(timeout=5)
        self.temporary.cleanup()

    def command(self, command, **values):
        body = urlencode({'cmd': command, **values}).encode()
        with socket.socket(socket.AF_UNIX) as channel:
            channel.connect(str(self.channel))
            channel.sendall(b'POST /command HTTP/1.0\r\nHost: paperos\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: '
                            + str(len(body)).encode() + b'\r\n\r\n' + body)
            answer = b''
            while block := channel.recv(4096):
                answer += block
        self.assertIn(b' 200 ', answer.split(b'\r\n', 1)[0], answer.decode())

    def seed_wallpapers(self, count=7):
        self.service.terminate()
        self.service.wait(timeout=5)
        cache = self.directory / 'data/lockscreen'
        cache.mkdir(parents=True, exist_ok=True)
        images = []
        for i in range(count):
            ident = hashlib.sha256(('wallpaper-' + str(i)).encode()).hexdigest()
            data = b'P5\n600 800\n255\n' + bytes([34 + i * 17]) * (600 * 800)
            (cache / (ident + '.pgm')).write_bytes(data)
            images.append({'ID': ident, 'SHA256': hashlib.sha256(data).hexdigest(),
                           'Title': '山川 ' + str(i + 1), 'Copyright': 'PaperOS test fixture',
                           'URL': 'https://res.public.onecdn.static.microsoft/creativeservice/' + ident + '.jpg'})
        index = {'Version': 1, 'Day': datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d'),
                 'Current': images[0]['ID'], 'Entries': images}
        (cache / 'index.json').write_text(json.dumps(index))
        self.service = subprocess.Popen([str(ROOT / 'build/host/paperos-services'), '--simulate',
                                         '--root', str(self.directory / 'data'), '--run-dir', str(self.directory / 'run')],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if self.channel.exists() and self.state.exists():
                rows = [line.split('\t') for line in self.state.read_text().splitlines()]
                if any(row[0] == 'wallpaper' and int(row[4]) == count for row in rows):
                    return images
            time.sleep(.025)
        self.fail('wallpaper fixture did not load')

    def render(self, screen='home', *extra, env=None):
        image = self.directory / 'screen.pgm'
        result = subprocess.run([str(self.binary), '--font', str(ROOT / 'assets/NotoSansCJKsc-Regular.otf'),
                                 '--app-root', str(self.apps), '--screen', screen, '--render', str(image),
                                 '--services-file', str(self.state), '--services-socket', str(self.channel),
                                 '--allow-commands', *extra], capture_output=True, env={**os.environ, 'TZ': 'CST-8', **(env or {})}, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return image.read_bytes().split(b'\n', 3)[3]

    @contextmanager
    def input_replies(self, replies):
        path = self.directory / 'weather-input.sock'
        requests, errors = [], []
        def receive(client, count):
            value = b''
            while len(value) < count:
                block = client.recv(count - len(value))
                if not block:
                    raise RuntimeError('input client closed during request')
                value += block
            return value
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path));server.listen(1);server.settimeout(6)
            def respond():
                try:
                    for status, value in replies:
                        with server.accept()[0] as client:
                            client.settimeout(4)
                            magic, flags, capacity, title_size, text_size = struct.unpack('!5I', receive(client, 20))
                            title = receive(client, title_size).decode()
                            initial = receive(client, text_size).decode()
                            requests.append((title, flags, initial))
                            encoded = value.encode()
                            if magic != 0x50494d31 or len(encoded) > capacity:
                                raise RuntimeError('invalid input request or oversized reply')
                            client.sendall(struct.pack('!3I', magic, status, len(encoded)) + encoded)
                except Exception as error:
                    errors.append(error)
            worker = threading.Thread(target=respond, daemon=True);worker.start()
            try:
                yield {'PAPEROS_INPUT_SOCKET': str(path)}, requests
            finally:
                worker.join(timeout=7)
                self.assertFalse(worker.is_alive(), 'input exchange did not finish')
                self.assertEqual(errors, [])

    def test_weather_region_uses_shared_keyboard_and_saves_coordinates(self):
        with self.input_replies([(0, '上海浦东'), (0, '31.23'), (0, '121.55')]) as (env, requests):
            result = self.render('weather', '--tap', '500', '140', '--tap', '500', '158',
                                 '--tap', '100', '200', '--tap', '100', '325', '--tap', '100', '450',
                                 '--tap', '450', '670', env=env)
        location = json.loads((self.directory / 'data/state.json').read_text())['WeatherLocation']
        self.assertEqual(location['Name'], '上海浦东')
        self.assertEqual((location['Latitude'], location['Longitude']), (31.23, 121.55))
        self.assertEqual([r[0] for r in requests], ['地区名称', '纬度：-90 至 90', '经度：-180 至 180'])
        self.assertEqual([r[1] for r in requests], [0, 4, 4])
        self.assertEqual(result, self.render('weather'))
        self.assertIn('weather-location\t上海浦东\t手动设置\t31.23\t121.55', self.state.read_text())

    def test_weather_cancel_and_back_keep_current_region(self):
        self.command('weather-location-set', name='杭州', latitude='30.27', longitude='120.15')
        before = json.loads((self.directory / 'data/state.json').read_text())['WeatherLocation']
        with self.input_replies([(1, '')]) as (env, requests):
            self.render('weather', '--tap', '500', '140', '--tap', '500', '158', '--tap', '100', '200',
                        '--tap', '50', '74', '--tap', '50', '74', env=env)
        self.assertEqual(requests[0][2], '杭州')
        self.assertEqual(before, json.loads((self.directory / 'data/state.json').read_text())['WeatherLocation'])

    def test_weather_search_uses_chinese_keyboard_and_offline_error_keeps_region(self):
        with self.input_replies([(0, '上海')]) as (env, requests):
            self.render('weather', '--tap', '500', '140', '--tap', '200', '240', env=env)
        self.assertEqual(requests[0][:2], ('搜索天气地区', 0))
        self.assertIn('请先连接 Wi-Fi', self.state.read_text())
        self.assertIn('weather-location\t北京市朝阳区', self.state.read_text())

    def test_power_settings_save_switches_and_return_to_lock_settings(self):
        self.render('lock-settings', '--tap', '260', '594', '--tap', '510', '158')
        config = json.loads((self.directory / 'data/state.json').read_text())
        self.assertFalse(config['Sleep']['Enabled'])
        self.assertTrue(config['Sleep']['USBKeepAwake'])
        image = self.render('power-settings', '--tap', '510', '318', '--tap', '50', '74')
        config = json.loads((self.directory / 'data/state.json').read_text())
        self.assertEqual(config['Lock']['PoweredMultiplier'], 10)
        self.assertEqual(config['Lock']['IdleSeconds'], 300)
        self.assertTrue(config['Sleep']['USBKeepAwake'])
        self.assertEqual(image, self.render('lock-settings'))

    def test_simulated_manual_sleep_preserves_unlocked_state(self):
        self.render('power-settings', '--tap', '300', '670')
        self.assertIn('未启用真正休眠', self.state.read_text())
        self.assertIn('lock\tfalse\t', self.state.read_text())

    def display_fixture(self):
        now = int(time.time())
        battery = self.directory / 'battery.tsv'
        battery.write_text('paperos-battery-v1\t7\n'
                           + f'summary\t{now-86400}\t{now}\t1\t580\t600\t1\t0\t0\t0\n'
                           + 'day\t2026-10-17\t1\t600\t580\t1\t79\n'
                           + f'point\t{now-600}\t80\tfalse\tfalse\npoint\t{now}\t79\tfalse\ttrue\n')
        home = self.directory / 'mihome.tsv'
        home.write_text('paperos-mihome-v1\t42\n'
                        + f'item\ttemperature\t温度\t客厅\t23.6\t°C\ttrue\tfalse\t{now}\tsensor.room_temperature\n'
                        + f'item\thumidity\t湿度\t客厅\t48\t%\ttrue\tfalse\t{now}\tsensor.room_humidity\n'
                        + f'item\tstate\t客厅灯\t客厅\t关闭\t-\ttrue\tfalse\t{now}\tlight.room\n')
        state = self.directory / 'display-fixture.tsv'
        state.write_text('paperos-services-v1\nlock\tfalse\t300\t1\n'
                         + f'battery\ttrue\t79\tDischarging\tfalse\t{now}\t{battery}\t7\t-\n'
                         + f'mihome\ttrue\tfalse\t{now}\t测试家庭\t{home}\t42\t已更新\n')
        return state, home

    def test_battery_icon_tabs_and_back_need_no_keyboard_or_commands(self):
        state, _ = self.display_fixture()
        extra = ('--services-file', str(state))
        image = self.render('home', *extra, '--tap', '550', '25')
        self.assertEqual(image, self.render('battery', *extra))
        self.assertNotEqual(image, self.render('battery', *extra, '--tap', '450', '260'))
        back = self.render('battery', *extra, '--tap', '50', '74')
        self.assertEqual(back, self.render('settings', *extra))

    def test_mihome_metric_state_tabs_and_stale_readings_are_distinct(self):
        state, home = self.display_fixture()
        extra = ('--services-file', str(state))
        fresh = self.render('mihome', *extra)
        devices = self.render('mihome', *extra, '--tap', '450', '220')
        self.assertNotEqual(fresh, devices)
        self.assertEqual(devices, self.render('mihome', *extra, '--tap', '450', '220', '--tap', '470', '290'))
        home.write_text(home.read_text().replace('\ttrue\tfalse\t', '\ttrue\ttrue\t'))
        self.assertNotEqual(fresh, self.render('mihome', *extra))

    def test_widgets_hide_reorder_and_persist_without_uninstalling_app(self):
        before = self.render()
        self.render('widgets', '--tap', '450', '185')  # hide the clock widget
        self.assertTrue((self.apps / 'org.paperos.alarm/run.sh').is_file())
        self.assertIn('14', (self.apps / '.widgets.conf').read_text())
        after = self.render()
        self.assertTrue(before != after)
        self.render('widgets', '--tap', '450', '185')  # restore it
        self.assertEqual((self.apps / '.widgets.conf').read_text().split()[-1], '15')
        self.render('widgets', '--tap', '520', '240')  # move time after date
        self.assertEqual((self.apps / '.widgets.conf').read_text().split()[:2], ['1', '0'])

    def test_alarm_created_and_toggled_through_real_native_touches(self):
        self.render('alarm', '--tap', '180', '600', '--tap', '170', '655')
        config = json.loads((self.directory / 'data/state.json').read_text())
        self.assertEqual(len(config['Alarms']), 1)
        self.assertEqual(config['Alarms'][0]['Hour'], 7)
        self.render('alarm', '--tap', '530', '363')
        config = json.loads((self.directory / 'data/state.json').read_text())
        self.assertFalse(config['Alarms'][0]['Enabled'])

    def test_countdown_survives_app_switch_and_returns_to_preserved_note(self):
        note = self.directory / 'note.txt'
        note.write_text('你好，未丢失的笔记', encoding='utf-8')
        self.command('timer-start', seconds='1')
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and '\nalert\t' not in self.state.read_text():
            time.sleep(.05)
        self.assertIn('\nalert\t', self.state.read_text())
        white = self.render('notes', '--note', str(note))
        black = self.render('notes', '--note', str(note), '--alert-invert')
        self.assertTrue(all(a + b == 255 for a, b in zip(white, black)), 'reminder phases must invert the same geometry')
        restored = self.render('notes', '--note', str(note), '--tap', '120', '662')
        self.assertTrue(restored != white)
        self.assertEqual(note.read_text(), '你好，未丢失的笔记')
        self.assertNotIn('\nalert\t', self.state.read_text())

    def test_uninstalling_alarm_cancels_its_scheduled_reminders(self):
        self.command('timer-start', seconds='100')
        subprocess.run([str(self.binary), '--app-root', str(self.apps), '--services-socket', str(self.channel),
                        '--remove', 'org.paperos.alarm'], check=True, capture_output=True)
        config = json.loads((self.directory / 'data/state.json').read_text())
        self.assertNotEqual(config['Timer']['State'], 'running')

    def test_time_settings_toggle_persists_and_offline_sync_preserves_manual_mode(self):
        automatic = self.render('settings', '--tap', '160', '440')
        self.assertIn('\nclock\ttrue\t', self.state.read_text())
        manual = self.render('settings', '--tap', '160', '440', '--tap', '535', '182')
        config = json.loads((self.directory / 'data/state.json').read_text())
        self.assertFalse(config['Clock']['Automatic'])
        self.assertTrue(automatic != manual)
        failed = self.render('settings', '--tap', '160', '440', '--tap', '485', '265')
        self.assertTrue(failed != manual)
        config = json.loads((self.directory / 'data/state.json').read_text())
        self.assertFalse(config['Clock']['Automatic'])
        self.assertEqual(config['Clock']['LastSync'], 0)


    def test_lock_is_global_and_unlock_restores_note_and_keyboard(self):
        note = self.directory / 'note.txt'
        note.write_text('锁屏前的未保存文字', encoding='utf-8')
        before = self.render('notes', '--note', str(note))
        self.command('lock-now')
        locked = self.render('notes', '--note', str(note))
        self.assertNotEqual(locked, before)
        self.assertEqual(locked, self.render('notes', '--note', str(note), '--tap', '450', '655'))
        restored = self.render('notes', '--note', str(note), '--swipe', '300', '740', '300', '420')
        self.assertEqual(restored, before)
        keyboard = self.render('keyboard', '--note', str(note))
        self.command('lock-now')
        self.assertEqual(locked, self.render('keyboard', '--note', str(note), '--tap', '550', '767'))
        self.assertEqual(keyboard, self.render('keyboard', '--note', str(note), '--swipe', '290', '735', '310', '405'))
        self.assertEqual(note.read_text(), '锁屏前的未保存文字')

    def test_settings_lock_and_idle_time_use_actual_service(self):
        self.render('settings', '--tap', '180', '540', '--tap', '450', '650')
        self.assertIn('\nlock\ttrue\t', self.state.read_text())
        self.render('home', '--swipe', '300', '710', '310', '450')
        self.assertIn('\nlock\tfalse\t', self.state.read_text())
        self.render('settings', '--tap', '180', '540', '--tap', '175', '215')
        config = json.loads((self.directory / 'data/state.json').read_text())
        self.assertEqual(config['Lock']['IdleSeconds'], 60)

    def test_tailnet_settings_switches_preserve_identity_and_return(self):
        self.service.terminate()
        self.service.wait(timeout=5)
        self.service = subprocess.Popen([
            str(ROOT / 'build/host/paperos-services'), '--simulate',
            '--root', str(self.directory / 'data'), '--run-dir', str(self.directory / 'run'),
            '--simulate-ip', '127.0.0.2', '--simulate-tailnet-ip', '100.101.102.103',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def row():
            return next((line.split('\t') for line in self.state.read_text().splitlines() if line.startswith('tailnet\t')), [])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if len(row()) == 11 and row()[4] == 'true':
                break
            time.sleep(.025)
        self.assertEqual(row()[7], '100.101.102.103')
        self.render('settings', '--tap', '100', '676')
        self.render('tailscale', '--tap', '540', '500')
        config = json.loads((self.directory / 'data/state.json').read_text())
        self.assertFalse(config['Tailnet']['AllowReceive'])
        self.render('tailscale', '--tap', '540', '150')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and row()[5] == 'true':
            time.sleep(.025)
        self.assertEqual(row()[2], 'false')
        self.render('tailscale', '--tap', '540', '150')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and (row()[2] != 'true' or row()[5] == 'true'):
            time.sleep(.025)
        self.assertEqual(row()[7], '100.101.102.103')
        config = json.loads((self.directory / 'data/state.json').read_text())
        self.assertTrue(config['Tailnet']['Enabled'])
        self.assertFalse(config['Tailnet']['AllowReceive'])
        self.assertEqual(self.render('tailscale', '--tap', '50', '74'), self.render('settings'))

    def test_tailnet_missing_client_never_invokes_host_network(self):
        self.render('tailscale', '--tap', '540', '150')
        self.assertIn('尚未安装', self.state.read_text())
        config_path = self.directory / 'data/state.json'
        if config_path.exists():
            self.assertFalse(json.loads(config_path.read_text())['Tailnet']['Enabled'])

    def test_reminder_overrides_lock_and_stop_returns_to_lock(self):
        self.command('lock-now')
        locked = self.render('calendar')
        self.command('timer-start', seconds='1')
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and '\nalert\t' not in self.state.read_text():
            time.sleep(.05)
        reminder = self.render('calendar')
        self.assertNotEqual(reminder, locked)
        restored = self.render('calendar', '--tap', '120', '665')
        # The lock clock/date can advance while the real countdown elapses.
        # Compare the wallpaper and lock controls below that dynamic region.
        self.assertEqual(restored[240 * 600:], locked[240 * 600:])
        self.assertIn('\nlock\ttrue\t', self.state.read_text())

    def test_wallpaper_fullscreen_preview_is_read_only_until_use(self):
        images = self.seed_wallpapers()
        index = self.directory / 'data/lockscreen/index.json'
        before = index.read_bytes()
        preview = self.render('lock-settings', '--tap', '350', '530', '--tap', '100', '260', '--tap', '300', '300')
        self.assertEqual(preview[400 * 600 + 300], 34)
        self.assertEqual(index.read_bytes(), before)
        self.assertIn('\nlock\tfalse\t', self.state.read_text())
        self.render('wallpapers', '--tap', '100', '260', '--tap', '425', '675')
        settings = json.loads(index.read_text())
        self.assertEqual(settings['Mode'], 'fixed')
        self.assertEqual(settings['Fixed']['ID'], images[0]['ID'])

    def test_wallpaper_favorites_filter_and_modes_through_native_controls(self):
        images = self.seed_wallpapers()
        self.render('wallpapers', '--tap', '300', '260', '--tap', '130', '675')
        index = self.directory / 'data/lockscreen/index.json'
        settings = json.loads(index.read_text())
        self.assertEqual([p['ID'] for p in settings['Favorites']], [images[1]['ID']])
        self.render('wallpapers', '--tap', '430', '150', '--tap', '100', '260',
                    '--tap', '70', '75', '--tap', '70', '75', '--tap', '300', '310')
        self.assertEqual(json.loads(index.read_text())['Mode'], 'favorites')
        self.render('lock-settings', '--tap', '500', '310')
        settings = json.loads(index.read_text())
        self.assertEqual(settings['Mode'], 'fixed')
        self.assertEqual(settings['Fixed']['ID'], images[1]['ID'])


class CalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        output = Path(cls.temporary.name) / 'calendar.so'
        subprocess.run(['cc', '-std=c11', '-shared', '-fPIC', str(ROOT / 'native/calendar.c'), '-o', str(output)], check=True)
        cls.library = ctypes.CDLL(str(output))
        cls.library.paperos_lunar.argtypes = [ctypes.c_int] * 3 + [ctypes.POINTER(ctypes.c_int)] * 3 + [ctypes.POINTER(ctypes.c_bool)]
        cls.library.paperos_lunar.restype = ctypes.c_bool
        cls.library.paperos_solar_term.argtypes = [ctypes.c_int] * 3
        cls.library.paperos_solar_term.restype = ctypes.c_char_p
        cls.library.paperos_festival_label.argtypes = [ctypes.c_int] * 3 + [ctypes.c_char_p, ctypes.c_size_t]
        cls.library.paperos_calendar_events.argtypes = cls.library.paperos_festival_label.argtypes
        cls.library.paperos_next_solar_term.argtypes = [ctypes.c_int] * 3 + [ctypes.POINTER(ctypes.c_int)] * 4
        cls.library.paperos_next_solar_term.restype = ctypes.c_char_p

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_known_lunar_dates_leap_month_and_range(self):
        for date, expected in [((2026, 10, 16), (2026, 9, 7, False)),
                               ((2026, 2, 17), (2026, 1, 1, False)),
                               ((2024, 2, 10), (2024, 1, 1, False)),
                               ((2023, 3, 22), (2023, 2, 1, True))]:
            values = [ctypes.c_int() for _ in range(3)]
            leap = ctypes.c_bool()
            self.assertTrue(self.library.paperos_lunar(*date, *(ctypes.byref(v) for v in values), ctypes.byref(leap)))
            self.assertEqual(tuple(v.value for v in values) + (leap.value,), expected)
        values = [ctypes.c_int() for _ in range(3)]
        leap = ctypes.c_bool()
        self.assertFalse(self.library.paperos_lunar(2101, 1, 1, *(ctypes.byref(v) for v in values), ctypes.byref(leap)))

    def events(self, y, m, d, festivals_only=False):
        output = ctypes.create_string_buffer(256)
        function = self.library.paperos_festival_label if festivals_only else self.library.paperos_calendar_events
        function(y, m, d, output, len(output))
        return output.value.decode('utf-8')

    def test_verified_solar_terms_and_cross_year_lookup(self):
        for date, label in [((2026, 2, 4), '立春'), ((2026, 3, 20), '春分'),
                            ((2026, 4, 5), '清明'), ((2026, 6, 21), '夏至'),
                            ((2026, 10, 8), '寒露'), ((2026, 10, 23), '霜降'),
                            ((2026, 12, 22), '冬至')]:
            self.assertEqual(self.library.paperos_solar_term(*date).decode(), label)
        values = [ctypes.c_int() for _ in range(4)]
        label = self.library.paperos_next_solar_term(2026, 10, 16, *(ctypes.byref(v) for v in values)).decode()
        self.assertEqual((label, *(v.value for v in values)), ('霜降', 2026, 10, 23, 7))
        label = self.library.paperos_next_solar_term(2026, 12, 31, *(ctypes.byref(v) for v in values)).decode()
        self.assertEqual((label, *(v.value for v in values)), ('小寒', 2027, 1, 5, 5))
        self.assertEqual(self.library.paperos_solar_term(2101, 1, 5), b'')
        self.assertEqual(self.library.paperos_next_solar_term(2100, 12, 31, *(ctypes.byref(v) for v in values)), b'')

    def test_festivals_include_short_new_year_eve_and_exclude_leap_months(self):
        for date, label in [((2026, 2, 16), '除夕'), ((2026, 2, 17), '春节'),
                            ((2026, 3, 3), '元宵节'), ((2026, 6, 19), '端午节'),
                            ((2026, 9, 25), '中秋节'), ((2026, 10, 18), '重阳节'),
                            ((2025, 1, 28), '除夕'), ((2024, 2, 9), '除夕')]:
            self.assertIn(label, self.events(*date))
        self.assertNotIn('龙抬头', self.events(2023, 3, 23))
        self.assertIn('龙抬头', self.events(2023, 2, 21))
        self.assertEqual(self.events(2020, 10, 1), '国庆节 · 中秋节')
        self.assertEqual(self.events(2026, 6, 21), '父亲节 · 夏至')
        self.assertEqual(self.events(2026, 5, 10), '母亲节')
        self.assertEqual(self.events(2026, 2, 30), '')


if __name__ == '__main__':
    unittest.main()
