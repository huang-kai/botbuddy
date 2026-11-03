"""名称迁移必须复用配置、登录态、锁与升级恢复入口。"""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from botbuddy.paths import data_directory, environment
from botbuddy.config.storage import SetupError, write_config
from botbuddy.skills.metadata import load_skill_metadata
from botbuddy.skills.runtime import skill_environment
from botbuddy.tools import install, update

ROOT = Path(__file__).resolve().parents[1]


class BrandMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        env = patch.dict(os.environ, {'HOME': str(self.root), 'PATH': os.environ['PATH']}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_home_selection_is_read_only_and_ambiguous_roots_require_selection(self):
        self.assertEqual(data_directory(), self.root / '.botbuddy')
        self.assertFalse(data_directory().exists())
        old = self.root / '.primebuddy'
        old.mkdir()
        self.assertEqual(data_directory(), old)
        new = self.root / '.botbuddy'
        new.mkdir()
        with self.assertRaisesRegex(ValueError, 'BOTBUDDY_HOME'):
            data_directory()
        with patch.dict(os.environ, PRIMEBUDDY_HOME=str(old)):
            self.assertEqual(data_directory(), old)
            with patch.dict(os.environ, BOTBUDDY_HOME=str(new)):
                self.assertEqual(data_directory(), new)

    def test_all_environment_aliases_use_new_name_first(self):
        for key in ('HOME', 'RUNTIME', 'LOG_DIR'):
            with patch.dict(os.environ, {'PRIMEBUDDY_' + key: 'old'}):
                self.assertEqual(environment(key), 'old')
                with patch.dict(os.environ, {'BOTBUDDY_' + key: 'new'}):
                    self.assertEqual(environment(key), 'new')

    def test_old_imports_share_module_state_and_exception_types(self):
        for name in ('config.storage', 'config.runtime', 'core.engine', 'skills.runtime'):
            self.assertIs(importlib.import_module('primebuddy.' + name),
                          importlib.import_module('botbuddy.' + name))
        result = subprocess.run([sys.executable, '-m', 'primebuddy', '--version'],
                                env=dict(os.environ, PYTHONPATH=str(ROOT / 'src')), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('BotBuddy 1.3.0', result.stdout)

    def test_old_skill_metadata_and_both_environment_names(self):
        skill = self.root / 'hello'
        (skill / 'cfg').mkdir(parents=True)
        (skill / 'SKILL.md').write_text('---\nname: hello\ndescription: test\n---\n')
        package = skill / 'cfg/pkg.yaml'
        package.write_text('primebuddy:\n  mode: exclusive\n')
        self.assertEqual(load_skill_metadata(skill)['mode'], 'exclusive')
        package.write_text('primebuddy:\n  mode: exclusive\nbotbuddy:\n  mode: task\n')
        with self.assertRaisesRegex(SetupError, '冲突'):
            load_skill_metadata(skill)
        env = skill_environment(skill, 'hello')
        for name in ('HOME', 'SKILL_DATA', 'SKILL_CONFIG'):
            self.assertEqual(env['BOTBUDDY_' + name], env['PRIMEBUDDY_' + name])

    def test_old_install_upgrades_in_place_preserving_data_and_shell(self):
        home = self.root / '.primebuddy'
        (home / 'src/primebuddy').mkdir(parents=True)
        (home / 'src/primebuddy/__init__.py').write_text("__version__ = '1.0.0'\n")
        (home / 'main.py').write_text('# old app\n')
        self.assertEqual(update.installed_version(home), '1.0.0')
        private = {'cfg/config.yaml': {'logging': {'directory': str(self.root / 'logs')}},
                   'cfg/providers.yaml': {'token': 'test-only'},
                   'cfg/skills/hello/config.yaml': {'keep': True}}
        for name, value in private.items():
            write_config(home / name, value)
        for name in ('data/hello/login.json', 'runtime/history.json', 'cfg/skills.yaml'):
            path = home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}\n')
            path.chmod(0o600)
        preserved = {p: p.read_bytes() for folder in ('cfg', 'data', 'runtime')
                     for p in (home / folder).rglob('*') if p.is_file()}
        (self.root / '.bashrc').write_text('export KEEP=yes\n# >>> PrimeBuddy PATH >>>\nold-path\n# <<< PrimeBuddy PATH <<<\n')
        with patch.object(install, 'prepare_logs'), patch.object(install, 'prepare_dependencies'):
            launcher = install.install(data_directory())
        self.assertEqual(launcher, home / 'bin/botbuddy')
        self.assertFalse((self.root / '.botbuddy').exists())
        for path, content in preserved.items():
            self.assertEqual(path.read_bytes(), content, str(path))
        for name in ('botbuddy', 'primebuddy'):
            result = subprocess.run([str(home / 'bin' / name), '--version'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('BotBuddy 1.3.0', result.stdout)
        shell = (self.root / '.bashrc').read_text()
        self.assertIn('export KEEP=yes', shell)
        self.assertNotIn('PrimeBuddy PATH', shell)
        self.assertEqual(shell.count('# >>> BotBuddy PATH >>>'), 1)

    def test_flat_legacy_provider_config_is_not_shadowed_by_new_defaults(self):
        home = self.root / '.primebuddy'
        write_config(home / 'config.yaml', {'voice': {'speech_cache_entries': 7}})
        write_config(home / 'providers.yaml', {'qianwen': {'api_key': 'test-only-old-key'}})
        previous = (home / 'providers.yaml').read_bytes()
        with patch.object(install, 'prepare_logs'), patch.object(install, 'prepare_dependencies'), \
                patch.object(install, 'configure_shell'):
            install.install(home)
        self.assertEqual((home / 'cfg/providers.yaml').read_bytes(), previous)
        self.assertEqual((home / 'cfg/providers.yaml').stat().st_mode & 0o777, 0o600)

    def test_both_launchers_guard_interrupted_updates_without_importing_source(self):
        home = self.root / 'app'
        install.stage_launcher(home, home)
        journal = home / '.update/transaction.json'
        journal.parent.mkdir()
        journal.write_text('{}')
        (journal.parent / 'runner.py').write_text('print("RECOVERED")\n')
        for name in ('botbuddy', 'primebuddy'):
            launcher = home / 'bin' / name
            blocked = subprocess.run([str(launcher), 'start'], capture_output=True, text=True)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn('update --recover', blocked.stderr)
            recovered = subprocess.run([str(launcher), 'update', '--recover'], capture_output=True, text=True)
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertIn('RECOVERED', recovered.stdout)

    def test_repository_transition_keeps_old_manifests_but_restricts_new_releases(self):
        from botbuddy.config.compatibility import validate_release, release_url
        for version, repository, filename, valid in (
                ('1.2.1', 'primebuddy', 'primebuddy-1.2.1.rpk', True),
                ('1.3.0', 'botbuddy', 'botbuddy-1.3.0.rpk', True),
                ('1.3.0', 'primebuddy', 'botbuddy-1.3.0.rpk', False),
                ('1.3.0', 'unexpected', 'botbuddy-1.3.0.rpk', False)):
            manifest = {'schema_version': 1, 'version': version, 'skills': {},
                        'framework': {'filename': filename, 'sha256': '0' * 64,
                                      'url': 'https://github.com/huang-kai/' + repository
                                             + '/releases/download/v' + version + '/' + filename}}
            with self.subTest(version=version, repository=repository):
                if valid:
                    self.assertEqual(validate_release(manifest), manifest)
                else:
                    with self.assertRaises(SetupError):
                        validate_release(manifest)
        self.assertEqual(release_url('1.3.0', 'release.json'),
                         'https://github.com/huang-kai/botbuddy/releases/download/v1.3.0/release.json')

    def test_old_ssh_config_block_is_replaced_without_changing_key(self):
        from botbuddy.integrations.primebot.ssh_setup import configure_host
        directory = self.root / '.ssh'
        directory.mkdir()
        path = directory / 'config'
        path.write_text('# >>> PrimeBuddy run@10.1.1.100 >>>\nold\n# <<< PrimeBuddy run@10.1.1.100 <<<\nHost example\n')
        key = directory / 'primebuddy/key'
        configure_host('run@10.1.1.100', key)
        self.assertNotIn('PrimeBuddy run@', path.read_text())
        self.assertIn(str(key), path.read_text())
        self.assertIn('Host example', path.read_text())


if __name__ == '__main__':
    unittest.main()
