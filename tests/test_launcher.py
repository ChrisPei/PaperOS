"""The app drawer launches installed software; catalog and management stay separate."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / 'build/host/paperos'


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='paperos-launcher-')
        self.directory = Path(self.temp.name)
        self.apps = self.directory / 'apps'
        self.packages = self.directory / 'packages'
        self.packages.mkdir()
        self.catalog = self.directory / 'catalog.tsv'
        self.catalog.write_text('paperos-store-v1\t1\nsort\tpopular\n')
        self.state = self.directory / 'state.tsv'
        self.state.write_text('paperos-services-v1\nstore\tfalse\tidle\t0\t1\t' + str(self.catalog) + '\tCached catalog\t-\t-\t-\n')
        self.environment = dict(os.environ, PAPEROS_SERVICE_SOCKET=str(self.directory / 'absent.sock'))

    def tearDown(self):
        self.temp.cleanup()

    def package(self, app_id, name, installed=True, version='1', widget=None):
        package = self.packages / (app_id + '.papp')
        package.mkdir(exist_ok=True)
        manifest = f'id={app_id}\nname={name}\nversion={version}\nexec=run.sh\ndescription=A real package fixture\n'
        if widget:
            manifest += 'widget=' + widget + '\n'
        (package / 'manifest.conf').write_text(manifest)
        (package / 'run.sh').write_text('#!/bin/sh\nexit 0\n')
        if installed:
            subprocess.run([str(BINARY), '--app-root', str(self.apps), '--install', str(package)], check=True, capture_output=True, env=self.environment)
        return package

    def entry(self, app_id, name, kind='papp', installed='', update=False):
        with self.catalog.open('a') as output:
            output.write(f'app\tsource:{app_id}\t{app_id}\t{name}\t2\t{installed or "-"}\t{kind}\tExample source\t1000\t-\tDownloadable package\t{str(update).lower()}\thttps://example.org/archive.zip\t' + 'a'*64 + '\t99\t2026-10-19\tutility\tExample source\n')

    def render(self, screen='apps', taps=(), swipes=()):
        image = self.directory / 'screen.pgm'
        command = [str(BINARY), '--font', str(ROOT / 'assets/NotoSansCJKsc-Regular.otf'), '--app-root', str(self.apps), '--packages', str(self.packages), '--services-file', str(self.state), '--screen', screen, '--render', str(image)]
        for x, y in taps:
            command.extend(['--tap', str(x), str(y)])
        for x0, y0, x1, y1 in swipes:
            command.extend(['--swipe', str(x0), str(y0), str(x1), str(y1)])
        result = subprocess.run(command, check=True, capture_output=True, env=self.environment, timeout=10)
        return image.read_bytes().split(b'255\n', 1)[1], result.stderr.decode()

    def core(self, image):
        return image[:590*600] + image[724*600:]

    def test_apps_is_an_installed_only_offline_drawer_even_with_a_large_store(self):
        self.package('org.paperos.koreader', 'KOReader')
        self.package('org.paperos.alarm', '闹钟', widget='clock')
        self.package('org.paperos.not-installed', '未安装的软件', installed=False)
        before, _ = self.render()
        for i in range(300):
            self.entry(f'koplugin.catalog{i}', f'Plugin {i}', kind='koplugin', installed='1' if i == 0 else '')
        self.entry('org.paperos.not-installed', '未安装的软件')
        (self.apps / 'reader-only.koplugin').mkdir()
        after, _ = self.render()
        self.assertEqual(before, after, 'Remote entries, local packages and reader plugins cannot become app tiles')
        _, log = self.render(taps=[(116, 215)])
        self.assertIn('PaperOS launch requested: org.paperos.koreader', log)
        _, log = self.render(taps=[(300, 215)])
        self.assertIn('PaperOS launch requested: org.paperos.alarm', log)
        for screen in ('home', 'settings', 'store', 'app-manager'):
            image, _ = self.render(screen, taps=[(300, 760)])
            self.assertEqual(image, before, screen)

    def test_store_requires_its_own_tile_and_returns_to_the_drawer(self):
        self.package('org.paperos.koreader', 'KOReader')
        self.entry('org.paperos.available', 'Available app')
        drawer, _ = self.render()
        store, _ = self.render('store')
        opened, log = self.render(taps=[(484, 540)])
        self.assertNotIn('launch requested', log)
        self.assertEqual(self.core(opened), self.core(store))
        self.assertNotEqual(self.core(store), self.core(drawer))
        returned, _ = self.render(taps=[(484, 540), (70, 75)])
        self.assertEqual(returned, drawer)
        unused, log = self.render(taps=[(300, 540)])
        self.assertEqual(unused, drawer)
        self.assertNotIn('launch requested', log)

    def test_settings_owns_application_management_and_its_back_navigation(self):
        self.package('org.paperos.alarm', '闹钟', widget='clock')
        manager, _ = self.render('app-manager')
        opened, _ = self.render('settings', taps=[(180, 440)])
        self.assertEqual(self.core(opened), self.core(manager))
        details, log = self.render('app-manager', taps=[(200, 270)])
        self.assertNotIn('launch requested', log, 'Selecting a management row must not start the app')
        self.assertNotEqual(details, manager)
        returned, _ = self.render('app-manager', taps=[(200, 270), (60, 75)])
        self.assertEqual(returned, manager)
        settings, _ = self.render('settings')
        back, _ = self.render('app-manager', taps=[(60, 75)])
        self.assertEqual(back, settings)

    def test_local_install_remove_and_reinstall_refresh_the_drawer_and_keep_data(self):
        app_id = 'org.paperos.clock'
        self.package(app_id, '独立时钟', installed=False)
        empty, _ = self.render()
        installed, _ = self.render('settings', taps=[(200, 440), (130, 630), (200, 205), (230, 430), (300, 760)])
        self.assertTrue((self.apps / app_id / 'run.sh').exists())
        self.assertNotEqual(installed, empty)
        _, log = self.render(taps=[(116, 215)])
        self.assertIn('launch requested: ' + app_id, log)
        data = self.apps / '.data' / app_id / 'saved.txt'
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_text('Reader progress and user content')
        self.render('app-manager', taps=[(200, 270), (230, 580)])
        self.assertTrue((self.apps / app_id).exists(), 'First tap only asks for uninstall confirmation')
        removed, _ = self.render('app-manager', taps=[(200, 270), (230, 580), (230, 580), (300, 760)])
        self.assertFalse((self.apps / app_id).exists())
        self.assertEqual(removed, empty)
        self.assertEqual(data.read_text(), 'Reader progress and user content')
        self.render('app-manager', taps=[(130, 630), (200, 205), (230, 430), (300, 760)])
        self.assertTrue((self.apps / app_id / 'run.sh').exists())
        self.assertEqual(data.read_text(), 'Reader progress and user content')

    def test_drawer_paging_swipes_keep_the_store_and_do_not_launch_on_a_swipe(self):
        for i in range(12):
            self.package(f'org.paperos.extra{i:02}', f'App {i:02}')
        first, _ = self.render()
        second, log = self.render(swipes=[(520, 400, 80, 400)])
        self.assertNotIn('launch requested', log)
        self.assertNotEqual(first, second)
        paged, _ = self.render(taps=[(520, 685)])
        self.assertEqual(paged, second)
        launched, log = self.render(taps=[(520, 685), (116, 215)])
        self.assertIn('launch requested: org.paperos.extra08', log)
        returned, _ = self.render(taps=[(520, 685), (484, 540), (60, 75)])
        self.assertEqual(returned, second)
        back, _ = self.render(taps=[(520, 685), (80, 685)])
        self.assertEqual(back, first)

    def test_local_package_paging_keeps_all_packages_reachable(self):
        for i in range(8):
            self.package(f'org.paperos.local{i:02}', f'Local {i:02}', installed=False)
        self.render('local-packages', taps=[(520, 685), (200, 205), (230, 430)])
        self.assertTrue((self.apps / 'org.paperos.local05' / 'manifest.conf').exists())
        self.assertFalse((self.apps / 'org.paperos.local00').exists())

    def test_plugins_have_a_management_tab_but_no_standalone_tile_or_store_uninstall(self):
        self.package('org.paperos.koreader', 'KOReader')
        drawer, _ = self.render()
        self.entry('koplugin.reader', 'Reader plugin', kind='koplugin', installed='1')
        self.assertEqual(self.render()[0], drawer)
        plugins, _ = self.render('app-manager', taps=[(300, 190)])
        details, _ = self.render('app-manager', taps=[(300, 190), (200, 270)])
        confirmation, _ = self.render('app-manager', taps=[(300, 190), (200, 270), (200, 625)])
        self.assertNotEqual(details, confirmation)
        back, _ = self.render('app-manager', taps=[(300, 190), (200, 270), (60, 75)])
        self.assertEqual(back, plugins)
        store_details, _ = self.render('store', taps=[(200, 270)])
        no_uninstall, _ = self.render('store', taps=[(200, 270), (200, 625)])
        self.assertEqual(store_details, no_uninstall)

    def test_store_categories_do_not_change_installed_management_or_drawer_order(self):
        self.package('org.paperos.koreader', 'KOReader')
        self.entry('org.paperos.catalog', 'Catalog native')
        self.entry('koplugin.reader', 'Reader plugin', kind='koplugin')
        all_entries, _ = self.render('store')
        native, _ = self.render('store', taps=[(300, 190)])
        plugins, _ = self.render('store', taps=[(490, 190)])
        self.assertNotEqual(all_entries[:590*600], native[:590*600])
        self.assertNotEqual(native[:590*600], plugins[:590*600])
        drawer, _ = self.render()
        back, _ = self.render('store', taps=[(490, 190), (300, 760)])
        self.assertEqual(back, drawer)

    def test_native_update_detail_returns_to_the_same_application_information(self):
        self.package('org.paperos.koreader', 'KOReader')
        self.entry('org.paperos.koreader', 'KOReader', installed='1', update=True)
        details, _ = self.render('app-manager', taps=[(200, 270)])
        returned, _ = self.render('app-manager', taps=[(200, 270), (200, 506), (60, 75)])
        self.assertEqual(details, returned)
        updates, _ = self.render('app-manager', taps=[(490, 190)])
        returned, _ = self.render('app-manager', taps=[(490, 190), (200, 270), (60, 75)])
        self.assertEqual(updates, returned)


if __name__ == '__main__':
    unittest.main()
