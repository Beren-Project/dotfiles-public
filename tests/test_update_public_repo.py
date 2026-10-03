"""Public synchronization uses only disposable source trees and Git repositories."""
import errno
import importlib.util
import io
import os
from pathlib import Path
import pty
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
with patch.object(sys, 'path', [str(ROOT/'scripts'), *sys.path]):
    spec = importlib.util.spec_from_file_location('update_public_repo', ROOT/'scripts/update_public_repo.py')
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)


def state(root):
    """Include Git metadata, permissions, and modification times when checking no writes."""
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mode,
                                         path.stat().st_mtime_ns)
            for path in root.rglob('*') if path.is_file() and not path.is_symlink()}


def without_colors(text):
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


class ColorRenderingTests(unittest.TestCase):
    def test_color_policy_modes_tty_and_no_color_presence(self):
        for mode in ['auto', 'always', 'never']:
            for tty in [False, True]:
                for no_color in [None, '', '1']:
                    with self.subTest(mode=mode, tty=tty, no_color=no_color):
                        out = io.StringIO()
                        out.isatty = lambda: tty
                        env = {} if no_color is None else {'NO_COLOR': no_color}
                        with patch.dict(os.environ, env, clear=True):
                            expected = no_color is None and (
                                mode == 'always' or mode == 'auto' and tty)
                            self.assertEqual(updater.color_enabled(mode, out), expected)

    def test_auto_stream_without_isatty_is_plain(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(updater.color_enabled('auto', object()))

    def test_rendering_preserves_plan_and_plain_text(self):
        before = {
            'changed': (b'+ context - embedded\n--- context\n+++ context\n-- old', 0o644),
            'gone': (b'deleted\n', 0o644),
        }
        after = {
            'changed': (b'+ context - embedded\n--- context\n+++ context\n++ new', 0o755),
            'added': (b'added\n', 0o644),
        }
        plain, colored = io.StringIO(), io.StringIO()
        plain_plan = updater.show_plan(before, after, {'obsolete'}, set(), True, plain)
        color_plan = updater.show_plan(before, after, {'obsolete'}, set(), True, colored,
                                       updater.TerminalColors(True))
        output = colored.getvalue()
        self.assertEqual(plain_plan, color_plan)
        self.assertEqual(without_colors(output), plain.getvalue())
        self.assertNotIn('\x1b', plain.getvalue())
        for code, label in [(32, 'ADD'), (33, 'CHANGE'), (31, 'DELETE'), (35, 'RMDIR')]:
            self.assertIn(f'\x1b[{code}m{label}\x1b[0m', output)
        for code, line in [
            (31, "--- public/'changed'"), (32, "+++ snapshot/'changed'"),
            (36, '@@ -1,4 +1,4 @@'), (31, '--- old'), (32, '+++ new'),
            (31, '-deleted'), (32, '+added'),
        ]:
            self.assertIn(f'\x1b[{code}m{line}\x1b[0m\n', output)
        for line in [' + context - embedded', ' --- context', ' +++ context',
                     '\\ No newline at end of file', '  mode 0644 -> 0755']:
            self.assertIn(line, output.splitlines())
        self.assertTrue(output.splitlines()[-1].startswith('Summary:'))
        self.assertNotIn('\x1b', output.splitlines()[-1])

    def test_style_resets_before_line_endings(self):
        colors = updater.TerminalColors(True)
        for ending in ['', '\n', '\r\n']:
            with self.subTest(ending=ending):
                self.assertEqual(colors.paint('+line'+ending, 32),
                                 '\x1b[32m+line\x1b[0m'+ending)


class UpdatePublicRepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base/'private'
        self.source.mkdir()
        self.target = self.base/'public'
        self.target.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'core.hooksPath', '/dev/null')
        self.git('config', 'commit.gpgsign', 'false')
        self.manifest(['.gitignore', 'home/.hidden', 'added.txt'])
        self.write(self.source, '.gitignore', '*.cache\n')
        self.write(self.source, 'home/.hidden', 'new hidden\n')
        self.write(self.source, 'added.txt', 'new file\n')
        self.write(self.source, '.git/private-history', 'never export')
        self.write(self.source, 'private-note', 'never export')
        self.write(self.source, 'public-export/added.txt', 'stale export')
        self.write(self.target, '.gitignore', '*.cache\n')
        self.write(self.target, 'home/.hidden', 'old hidden\n')
        self.write(self.target, 'obsolete/nested/.old', 'delete me\n')
        self.commit()

    def git(self, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
        return subprocess.check_output(['git', '-C', str(self.target), *args], env=env,
                                       stderr=subprocess.PIPE)

    def commit(self):
        self.git('add', '-A')
        self.git('commit', '-qm', 'fixture')

    def write(self, root, name, content):
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def manifest(self, names):
        (self.source/'public-files.txt').write_text('\n'.join(names)+'\n')

    def sync(self, **kwargs):
        out = io.StringIO()
        updater.update(self.source, self.target, out=out, **kwargs)
        return out.getvalue()

    def cli_fixture(self):
        scripts = self.source/'scripts'
        scripts.mkdir(exist_ok=True)
        for name in ['update_public_repo.py', 'export_public.py', 'terminal_colors.py']:
            shutil.copy2(ROOT/'scripts'/name, scripts/name)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('GIT_') and key != 'NO_COLOR'}
        command = [sys.executable, '-B', str(scripts/'update_public_repo.py'), '--diff']
        return command, env

    def tty_output(self, command, env):
        master, slave = pty.openpty()
        try:
            with subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                  stdout=slave, stderr=subprocess.PIPE,
                                  start_new_session=True) as child:
                os.close(slave)
                slave = None
                output = bytearray()
                deadline = time.monotonic()+10
                while time.monotonic() < deadline:
                    if not select.select([master], [], [], 0.1)[0]:
                        continue
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                        break  # Linux PTYs report EIO when their slave closes.
                    if not chunk:
                        break
                    output.extend(chunk)
                else:
                    child.kill()
                    self.fail('CLI did not finish in its disposable PTY')
                _, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, stderr)
                return output.decode()
        finally:
            os.close(master)
            if slave is not None:
                os.close(slave)

    def assert_refused_unchanged(self, **kwargs):
        before = state(self.target)
        with self.assertRaises((ValueError, OSError)):
            self.sync(apply=True, **kwargs)
        self.assertEqual(state(self.target), before)

    def test_preview_additions_changes_deletions_hidden_files_and_diff(self):
        before, source_before = state(self.target), state(self.source)
        output = self.sync(show_diff=True)
        self.assertIn("ADD     'added.txt'", output)
        self.assertIn("CHANGE  'home/.hidden'", output)
        self.assertIn("DELETE  'obsolete/nested/.old'", output)
        self.assertIn("--- public/'home/.hidden'", output)
        self.assertIn("+++ snapshot/'home/.hidden'", output)
        self.assertIn('-old hidden\n+new hidden\n', output)
        self.assertIn('add=1, change=1, delete=1, unchanged=1', output)
        self.assertEqual(state(self.target), before)
        self.assertEqual(state(self.source), source_before)

    def test_apply_mirrors_snapshot_preserves_git_and_is_idempotent_after_commit(self):
        git_before, source_before = state(self.target/'.git'), state(self.source)
        output = self.sync(apply=True)
        self.assertIn('Applied and verified', output)
        files, directories = updater.inventory(self.target, preserve_git=True)
        self.assertEqual(set(files), {'.gitignore', 'home/.hidden', 'added.txt'})
        self.assertEqual(directories, {'home'})
        self.assertEqual((self.target/'added.txt').read_text(), 'new file\n')
        self.assertEqual((self.target/'home/.hidden').read_text(), 'new hidden\n')
        self.assertEqual(state(self.target/'.git'), git_before)
        self.assertEqual(state(self.source), source_before)
        self.assertEqual(self.git('diff', '--cached', '--name-only'), b'')
        self.assertIn('add=0, change=0, delete=0', self.sync())
        self.assert_refused_unchanged()  # The first apply left unstaged changes.
        self.commit()
        before = state(self.target)
        self.assertIn('add=0, change=0, delete=0', self.sync(apply=True))
        self.assertEqual(state(self.target), before)

    def test_dirty_modified_staged_untracked_and_ignored_destinations(self):
        for kind in ['modified', 'staged', 'untracked', 'ignored']:
            with self.subTest(kind=kind):
                if kind in ['modified', 'staged']:
                    self.write(self.target, 'home/.hidden', f'local edit {kind}')
                    if kind == 'staged': self.git('add', 'home/.hidden')
                else:
                    self.write(self.target, 'local.cache' if kind == 'ignored' else 'local.txt', 'local edit')
                self.assertIn('Destination has existing changes', self.sync())
                self.assert_refused_unchanged()
                if kind == 'ignored': (self.target/'local.cache').unlink()
                else: self.commit()

    def test_source_symlinks_missing_files_and_unsafe_manifest(self):
        good = (self.source/'public-files.txt').read_text()
        for name in ['../escape', '/absolute', '.git/private-history',
                     'reference/private', 'home/.gitconfig.local', 'missing',
                     'added.txt\nadded.txt']:
            with self.subTest(name=name):
                self.manifest([name])
                self.assert_refused_unchanged()
        (self.source/'public-files.txt').write_text(good)
        outside = self.write(self.base, 'outside', 'do not copy')
        hidden = self.source/'home/.hidden'
        hidden.unlink()
        hidden.symlink_to(outside)
        self.assert_refused_unchanged()
        hidden.unlink()
        shutil.rmtree(self.source/'home')
        (self.source/'home').symlink_to(self.base, target_is_directory=True)
        self.assert_refused_unchanged()

    def test_empty_snapshot_is_refused(self):
        (self.source/'public-files.txt').write_text('')
        self.assert_refused_unchanged()

    def test_manifest_and_source_root_symlinks(self):
        manifest = self.source/'public-files.txt'
        manifest.rename(self.source/'list')
        manifest.symlink_to(self.source/'list')
        self.assert_refused_unchanged()
        alias = self.base/'source-link'
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            updater.update(alias, self.target)

    def test_invalid_destination_missing_non_git_bare_and_subdirectory(self):
        plain = self.base/'plain'
        plain.mkdir()
        bare = self.base/'bare'
        subprocess.run(['git', 'init', '-q', '--bare', str(bare)], check=True)
        subdir = self.target/'subdir'
        subdir.mkdir()
        for target in [self.base/'missing', plain, bare, subdir]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                updater.update(self.source, target, apply=True)

    def test_overlapping_source_and_destination(self):
        for root, target in [(self.source, self.source), (self.base, self.target),
                             (self.target/'nested-source', self.target)]:
            with self.subTest(root=root, target=target), self.assertRaisesRegex(ValueError, 'separate'):
                updater.update(root, target, apply=True)

    def test_destination_symlinks_and_git_metadata_symlink(self):
        alias = self.base/'target-link'
        alias.symlink_to(self.target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            updater.update(self.source, alias, apply=True)
        outside = self.write(self.base, 'outside', 'keep me')
        hidden = self.target/'home/.hidden'
        hidden.unlink()
        hidden.symlink_to(outside)
        self.assert_refused_unchanged()
        self.assertEqual(outside.read_text(), 'keep me')
        hidden.unlink()
        (self.target/'home').rmdir()
        (self.target/'home').symlink_to(self.base, target_is_directory=True)
        self.assert_refused_unchanged()
        (self.target/'home').unlink()
        (self.target/'.git').rename(self.base/'metadata')
        (self.target/'.git').symlink_to(self.base/'metadata', target_is_directory=True)
        self.assert_refused_unchanged()

    def test_nested_git_special_files_and_hardlinks(self):
        nested = self.target/'nested/.git'
        nested.mkdir(parents=True)
        self.assert_refused_unchanged()
        nested.rmdir()
        nested.write_text('gitdir: elsewhere\n')
        self.assert_refused_unchanged()
        nested.unlink()
        fifo = self.target/'fifo'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, 'non-regular'):
            self.sync(apply=True)
        fifo.unlink()
        outside = self.write(self.base, 'outside', 'keep me')
        os.link(outside, self.target/'linked')
        self.assert_refused_unchanged()
        self.assertEqual(outside.read_text(), 'keep me')

    def test_index_flags_cannot_hide_local_changes(self):
        for flag in ['assume-unchanged', 'skip-worktree']:
            with self.subTest(flag=flag):
                self.git('update-index', '--'+flag, 'home/.hidden')
                self.write(self.target, 'home/.hidden', f'hidden local edit {flag}')
                self.assert_refused_unchanged()
                self.git('update-index', '--no-'+flag, 'home/.hidden')
                self.commit()

    def test_submodule_is_refused(self):
        revision = self.git('rev-parse', 'HEAD').decode().strip()
        self.git('update-index', '--add', '--cacheinfo', f'160000,{revision},submodule')
        self.assert_refused_unchanged()

    def test_file_directory_transitions_and_modes(self):
        self.manifest(['.gitignore', 'home', 'added.txt/child'])
        shutil.rmtree(self.source/'home')
        self.write(self.source, 'home', 'directory becomes file\n')
        (self.source/'added.txt').unlink()
        child = self.write(self.source, 'added.txt/child', 'file becomes directory\n')
        child.chmod(0o755)
        self.write(self.target, 'added.txt', 'old file\n')
        self.commit()
        self.sync(apply=True)
        self.assertTrue((self.target/'home').is_file())
        self.assertEqual((self.target/'added.txt/child').stat().st_mode & 0o777, 0o755)
        self.commit()
        child.chmod(0o644)
        self.assertIn('mode 0755 -> 0644', self.sync())
        self.sync(apply=True)
        self.assertEqual((self.target/'added.txt/child').stat().st_mode & 0o777, 0o644)

    def test_destination_changed_during_export_is_refused(self):
        real_export = updater.export
        def concurrent_export(root, snapshot):
            real_export(root, snapshot)
            self.write(self.target, 'added-concurrently', 'local edit')
        before = (self.target/'home/.hidden').read_bytes()
        with patch.object(updater, 'export', side_effect=concurrent_export):
            with self.assertRaisesRegex(ValueError, 'changed during preflight'):
                self.sync(apply=True)
        self.assertEqual((self.target/'home/.hidden').read_bytes(), before)
        self.assertTrue((self.target/'obsolete/nested/.old').exists())

    def test_binary_diff_is_not_dumped(self):
        (self.source/'added.txt').write_bytes(b'\x00\xff')
        self.assertIn('diff omitted', self.sync(show_diff=True))
        self.sync(apply=True)
        self.assertEqual((self.target/'added.txt').read_bytes(), b'\x00\xff')

    def test_binary_and_non_utf8_suppression_with_colors(self):
        for contents in [b'binary\x00payload', b'invalid\xffpayload']:
            for mode in ['auto', 'always', 'never']:
                with self.subTest(contents=contents, mode=mode):
                    (self.source/'added.txt').write_bytes(contents)
                    with patch.dict(os.environ, {}, clear=True):
                        output = self.sync(show_diff=True, color=mode)
                    self.assertIn('  Binary or non-UTF-8 contents differ; diff omitted.\n', output)
                    self.assertNotIn("+++ snapshot/'added.txt'", output)
                    self.assertNotIn('payload', output)
        for mode in ['auto', 'always', 'never']:
            with self.subTest(apply_mode=mode):
                clone = self.base/f'binary-{mode}'
                shutil.copytree(self.target, clone)
                updater.update(self.source, clone, apply=True, show_diff=True,
                               out=io.StringIO(), color=mode)
                self.assertEqual((clone/'added.txt').read_bytes(), contents)

    def test_cli_captured_and_redirected_color_modes(self):
        command, env = self.cli_fixture()
        command += ['--target', str(self.target)]
        before, source_before = state(self.target), state(self.source)
        for option, colored in [(None, False), ('auto', False), ('always', True), ('never', False)]:
            with self.subTest(option=option):
                args = command if option is None else command+[f'--color={option}']
                result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual('\x1b[' in result.stdout, colored)
                self.assertIn("ADD     'added.txt'", without_colors(result.stdout))
        with (self.base/'diff.txt').open('w') as output:
            result = subprocess.run(command, env=env, stdout=output,
                                    stderr=subprocess.PIPE, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('\x1b', (self.base/'diff.txt').read_text())
        self.assertEqual(state(self.target), before)
        self.assertEqual(state(self.source), source_before)

    def test_cli_tty_modes_and_no_color(self):
        command, env = self.cli_fixture()
        command += ['--target', str(self.target)]
        before, source_before = state(self.target), state(self.source)
        for option, colored in [(None, True), ('auto', True), ('always', True), ('never', False)]:
            with self.subTest(option=option):
                args = command if option is None else command+[f'--color={option}']
                self.assertEqual('\x1b[' in self.tty_output(args, env), colored)
        for value in ['', '1']:
            for mode in ['auto', 'always', 'never']:
                with self.subTest(no_color=value, mode=mode):
                    args = command+[f'--color={mode}']
                    no_color_env = {**env, 'NO_COLOR': value}
                    self.assertNotIn('\x1b', self.tty_output(args, no_color_env))
                    captured = subprocess.run(args, env=no_color_env, capture_output=True,
                                              text=True, timeout=10)
                    self.assertEqual(captured.returncode, 0, captured.stderr)
                    self.assertNotIn('\x1b', captured.stdout)
        self.assertEqual(state(self.target), before)
        self.assertEqual(state(self.source), source_before)

    def test_cli_apply_results_and_exit_codes_across_color_modes(self):
        command, env = self.cli_fixture()
        (self.source/'added.txt').chmod(0o755)
        expected_files = {
            name: ((self.source/name).read_bytes(), (self.source/name).stat().st_mode & 0o777)
            for name in (self.source/'public-files.txt').read_text().splitlines()
        }
        source_before = state(self.source)
        for mode in ['auto', 'always', 'never']:
            with self.subTest(mode=mode):
                clone = self.base/f'apply-{mode}'
                shutil.copytree(self.target, clone)
                git_before = state(clone/'.git')
                args = command+['--target', str(clone), '--apply', f'--color={mode}']
                applied = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(applied.returncode, 0, applied.stderr)
                self.assertEqual('\x1b[' in applied.stdout, mode == 'always')
                files, directories = updater.inventory(clone, preserve_git=True)
                self.assertEqual(files, expected_files)
                self.assertEqual(directories, {'home'})
                self.assertEqual(state(clone/'.git'), git_before)
                before_refusal = state(clone)
                refused = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(refused.returncode, 2)
                self.assertIn('not clean', refused.stderr)
                self.assertEqual(state(clone), before_refusal)
        self.assertEqual(state(self.source), source_before)

    def test_cli_default_destination_and_git_environment_overrides(self):
        (self.base/'repo/scripts').mkdir(parents=True)
        for name in ['update_public_repo.py', 'export_public.py', 'terminal_colors.py']:
            shutil.copy2(ROOT/'scripts'/name, self.base/'repo/scripts'/name)
        shutil.copytree(self.source, self.base/'repo', dirs_exist_ok=True)
        (self.base/'project').mkdir()
        self.target.rename(self.base/'project/dotfiles-public')
        self.target = self.base/'project/dotfiles-public'
        before = state(self.target)
        source_before = state(self.base/'repo')
        env = {**os.environ, 'HOME': str(self.base),
               'GIT_DIR': str(self.base/'wrong-git'), 'GIT_WORK_TREE': str(self.source)}
        env.pop('PYTHONDONTWRITEBYTECODE', None)
        command = [sys.executable, str(self.base/'repo/scripts/update_public_repo.py')]
        preview = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn('Preview only', preview.stdout)
        self.assertEqual(state(self.target), before)
        self.assertEqual(state(self.base/'repo'), source_before)
        applied = subprocess.run(command+['--apply'], env=env, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.write(self.target, 'local.txt', 'dirty')
        refused = subprocess.run(command+['--apply'], env=env, capture_output=True, text=True)
        self.assertEqual(refused.returncode, 2)
        self.assertIn('not clean', refused.stderr)


if __name__ == '__main__':
    unittest.main()
