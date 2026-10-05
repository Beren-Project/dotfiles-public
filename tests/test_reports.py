"""Read-only reports against controlled fixtures."""
import contextlib
import errno
import importlib.util
import io
import json
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
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    with patch.object(sys, 'path', [str(ROOT/'scripts'), *sys.path]):
        spec.loader.exec_module(result)
    return result
comparison = module('compare_configs')
dependencies = module('check_dependencies')


class ComparisonColorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.repo = self.base/'repo'
        self.source = self.repo/'home'
        self.target = self.base/'target'
        self.source.mkdir(parents=True)
        self.target.mkdir()
        self.context = '+ literal context - embedded\n--- context\n+++ context\n'
        (self.source/'changed').write_text(self.context+'repository value')
        (self.target/'changed').write_text(self.context+'target value')
        for root in [self.source, self.target]:
            (root/'same').write_text('identical\n')
        (self.repo/'managed-files.txt').write_text('changed\nsame\n')
        scripts = self.repo/'scripts'
        scripts.mkdir()
        for name in ['compare_configs.py', 'terminal_colors.py']:
            shutil.copy2(ROOT/'scripts'/name, scripts/name)
        self.command = [sys.executable, str(scripts/'compare_configs.py'),
                        '--target', str(self.target), '--diff']
        self.env = {key: value for key, value in os.environ.items() if key != 'NO_COLOR'}

    def state(self, extra_roots=()):
        # Include directories, symlinks, modes, and mtimes to detect any writes.
        return {
            str(path): (path.lstat().st_mode, path.lstat().st_mtime_ns,
                        os.readlink(path) if path.is_symlink() else
                        path.read_bytes() if path.is_file() else None)
            for root in [self.repo, self.target, *extra_roots]
            for path in [root, *root.rglob('*')]
        }

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
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                else:
                    child.kill()
                    self.fail('Comparison did not finish in its disposable PTY')
                _, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 1, stderr)
                return output.decode()
        finally:
            os.close(master)
            if slave is not None:
                os.close(slave)

    def test_colors_preserve_previous_text_counts_direction_and_read_only_state(self):
        expected = (
            'DIFFERENT     changed\n'
            '--- repository/changed\n+++ target/changed\n@@ -1,4 +1,4 @@\n'
            ' + literal context - embedded\n --- context\n +++ context\n'
            '-repository value\n\\ No newline at end of file\n'
            '+target value\n\\ No newline at end of file\n'
            'IDENTICAL     same\nSummary: DIFFERENT=1, IDENTICAL=1\n'
        )
        before = self.state()
        for mode in ['auto', 'always', 'never']:
            with self.subTest(mode=mode), patch.dict(os.environ, self.env, clear=True):
                out = io.StringIO()
                self.assertEqual(comparison.compare(self.source, self.target, True, out,
                                                    color=mode), 1)
                text = out.getvalue()
                self.assertEqual(re.sub(r'\x1b\[[0-9;]*m', '', text), expected)
                self.assertEqual('\x1b' in text, mode == 'always')
                if mode == 'always':
                    self.assertIn('\x1b[33mDIFFERENT\x1b[0m     changed\n', text)
                    for code, line in [
                        (31, '--- repository/changed'), (32, '+++ target/changed'),
                        (36, '@@ -1,4 +1,4 @@'), (31, '-repository value'), (32, '+target value'),
                    ]:
                        self.assertIn(f'\x1b[{code}m{line}\x1b[0m\n', text)
                    for line in [' + literal context - embedded', ' --- context', ' +++ context',
                                 '\\ No newline at end of file', 'IDENTICAL     same',
                                 'Summary: DIFFERENT=1, IDENTICAL=1']:
                        self.assertIn(line, text.splitlines())
        self.assertEqual(self.state(), before)

    def test_status_colors_errors_and_binary_suppression(self):
        for name in ['missing', 'linked', 'directory', 'unreadable', 'blocked/child']:
            path = self.source/name
            path.parent.mkdir(exist_ok=True)
            path.write_text('original\n')
        (self.target/'linked').symlink_to(self.source/'same')
        (self.target/'directory').mkdir()
        (self.target/'blocked').write_text('file blocks parent directory')
        (self.target/'unreadable').write_text('denied')
        for name, contents in [('binary', b'\x00payload'), ('non-utf8', b'\xffpayload')]:
            (self.source/name).write_text('repository\n')
            (self.target/name).write_bytes(contents)
        original = Path.read_bytes
        def denied(path):
            if path == self.target/'unreadable':
                raise PermissionError('fixture denied')
            return original(path)
        before = self.state()
        outputs = []
        for mode in ['always', 'never']:
            out = io.StringIO()
            with patch.dict(os.environ, self.env, clear=True), patch.object(Path, 'read_bytes', denied):
                self.assertEqual(comparison.compare(self.source, self.target, True, out,
                                                    color=mode), 2)
            outputs.append(out.getvalue())
        colored, plain = outputs
        self.assertEqual(re.sub(r'\x1b\[[0-9;]*m', '', colored), plain)
        for status in ['MISSING', 'SYMLINK', 'TYPE CONFLICT', 'UNREADABLE']:
            self.assertIn(f'\x1b[31m{status}\x1b[0m', colored)
        self.assertIn('Cannot read unreadable: fixture denied', colored.splitlines())
        self.assertEqual(colored.count('diff omitted'), 2)
        self.assertNotIn('payload', colored)
        self.assertNotIn('--- repository/binary', colored)
        self.assertNotIn('--- repository/non-utf8', colored)
        self.assertIn('Summary: DIFFERENT=3, IDENTICAL=1, MISSING=1, SYMLINK=1, '
                      'TYPE CONFLICT=2, UNREADABLE=1', colored.splitlines())
        self.assertEqual(self.state(), before)

    def test_auto_uses_current_stdout_and_explicit_output_stream(self):
        with patch.dict(os.environ, self.env, clear=True):
            tty = io.StringIO()
            tty.isatty = lambda: True
            with contextlib.redirect_stdout(tty):
                self.assertEqual(comparison.compare(self.source, self.target), 1)
                captured = io.StringIO()
                self.assertEqual(comparison.compare(self.source, self.target, out=captured), 1)
            self.assertIn('\x1b[33mDIFFERENT\x1b[0m', tty.getvalue())
            self.assertNotIn('\x1b', captured.getvalue())

    def test_cli_tty_captured_redirected_modes_and_no_color(self):
        before = self.state()
        for mode, tty_color, pipe_color in [(None, True, False), ('auto', True, False),
                                           ('always', True, True), ('never', False, False)]:
            with self.subTest(mode=mode):
                command = self.command if mode is None else self.command+[f'--color={mode}']
                self.assertEqual('\x1b' in self.tty_output(command, self.env), tty_color)
                result = subprocess.run(command, env=self.env, capture_output=True,
                                        text=True, timeout=10)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual('\x1b' in result.stdout, pipe_color)
        for value in ['', '1']:
            for mode in ['auto', 'always', 'never']:
                with self.subTest(no_color=value, mode=mode):
                    command = self.command+[f'--color={mode}']
                    env = {**self.env, 'NO_COLOR': value}
                    self.assertNotIn('\x1b', self.tty_output(command, env))
                    result = subprocess.run(command, env=env, capture_output=True,
                                            text=True, timeout=10)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertNotIn('\x1b', result.stdout)
        with (self.base/'config.diff').open('w') as output:
            result = subprocess.run(self.command, env=self.env, stdout=output,
                                    stderr=subprocess.PIPE, timeout=10)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('\x1b', (self.base/'config.diff').read_text())
        self.assertEqual(self.state(), before)

    def test_cli_exit_codes_across_modes(self):
        invalid_repo = self.base/'invalid'
        shutil.copytree(self.repo, invalid_repo)
        (invalid_repo/'managed-files.txt').write_text('../unsafe\n')
        before = self.state([invalid_repo])
        for mode in ['auto', 'always', 'never']:
            with self.subTest(mode=mode):
                command = self.command+[f'--color={mode}']
                different = subprocess.run(command, env=self.env, capture_output=True, timeout=10)
                self.assertEqual(different.returncode, 1, different.stderr)
                # Reading the repository as the target exercises all-identical exit 0.
                identical = subprocess.run(command+['--target', str(self.source)], env=self.env,
                                           capture_output=True, timeout=10)
                self.assertEqual(identical.returncode, 0, identical.stderr)
                self.assertIn(b'IDENTICAL=2', identical.stdout)
                self.assertNotIn(b'\x1b', identical.stdout)
                error = subprocess.run(
                    [sys.executable, str(invalid_repo/'scripts/compare_configs.py'),
                     '--target', str(self.target), f'--color={mode}'],
                    env=self.env, capture_output=True, timeout=10)
                self.assertEqual(error.returncode, 2)
                self.assertIn(b'Invalid managed file manifest', error.stderr)
        self.assertEqual(self.state([invalid_repo]), before)


class ReportTests(unittest.TestCase):
    def test_comparison_statuses_diffs_and_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); source=base/'source'; target=base/'target'
            source.mkdir(); target.mkdir()
            for name in ['same','changed','missing','binary','linked','directory','parent/child']:
                src=source/name; src.parent.mkdir(exist_ok=True); src.write_bytes(b'original\n')
            (target/'same').write_bytes(b'original\n')
            (target/'changed').write_bytes(b'new\n')
            (target/'binary').write_bytes(b'\x00\xff')
            (target/'linked').symlink_to(source/'same')
            (target/'directory').mkdir()
            (target/'parent').symlink_to(source)
            (target/'unrelated').write_text('private contents')
            before={str(p):p.read_bytes() for p in base.rglob('*') if p.is_file()}
            output=io.StringIO()
            self.assertEqual(comparison.compare(source,target,out=output),1)
            text=output.getvalue()
            for state in ['IDENTICAL','DIFFERENT','MISSING','SYMLINK','TYPE CONFLICT']:
                self.assertIn(state,text)
            self.assertNotIn('private contents',text); self.assertNotIn('unrelated',text)
            self.assertNotIn('original',text)
            diff=io.StringIO(); comparison.compare(source,target,True,diff)
            self.assertIn('--- repository/changed',diff.getvalue())
            self.assertIn('+++ target/changed',diff.getvalue())
            self.assertIn('diff omitted',diff.getvalue())
            self.assertEqual(before,{str(p):p.read_bytes() for p in base.rglob('*') if p.is_file()})

    def test_identical_unreadable_and_source_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); source=base/'source'; target=base/'target'
            source.mkdir(); target.mkdir()
            (source/'file').write_text('same'); (target/'file').write_text('same')
            self.assertEqual(comparison.compare(source,target,out=io.StringIO()),0)
            original=Path.read_bytes
            def denied(path):
                if path == target/'file': raise PermissionError('fixture denied')
                return original(path)
            with patch.object(Path,'read_bytes',denied):
                output=io.StringIO()
                self.assertEqual(comparison.compare(source,target,out=output),2)
                self.assertIn('UNREADABLE',output.getvalue())
            (source/'link').symlink_to(source/'file')
            with self.assertRaises(ValueError): comparison.compare(source,target,out=io.StringIO())
            (source/'directory').mkdir()
            for name in ['missing', 'directory']:
                with self.assertRaises(ValueError):
                    comparison.compare(source,target,out=io.StringIO(),names=[name])

    def test_dependency_paths_and_xdg(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); config=base/'home'; (config/'.config/mermaid').mkdir(parents=True)
            (base/'scripts').mkdir(); bindir=base/'bin'; bindir.mkdir()
            for name in ['gh','browser','zsh']:
                exe=bindir/name; exe.write_text('#!/bin/sh\nexit 99\n'); exe.chmod(0o755)
            (config/'.gitconfig').write_text(f'[credential "https://github.com"]\nhelper = !{base}/missing/gh auth git-credential\n')
            (config/'.config/mermaid/pptr.json').write_text(json.dumps({'executablePath':str(base/'missing/browser')}))
            (base/'scripts/zsh-plugins.json').write_text('{"zsh-example": {}}')
            data=base/'data'; plugin=data/'zsh/plugins/zsh-example/zsh-example.zsh'
            plugin.parent.mkdir(parents=True); plugin.write_text('# fixture')
            out=io.StringIO()
            dependencies.report(base,base/'live',{'PATH':str(bindir),'XDG_DATA_HOME':str(data)},out)
            self.assertIn('FOUND: zsh',out.getvalue()); self.assertIn('MISSING: delta',out.getvalue())
            self.assertIn('PATH MISMATCH:',out.getvalue()); self.assertIn(f'FOUND: {plugin}',out.getvalue())
            self.assertIn('optional generated integration file',out.getvalue())
            self.assertIn('MISSING: eza',out.getvalue())
            for name in ['uv', 'uvx', 'juliaup', 'julia']:
                self.assertIn(f'MISSING: {name} — optional Cargo-managed', out.getvalue())
            self.assertNotIn('.local/bin/env', out.getvalue())
            self.assertNotIn('.juliaup/bin', out.getvalue())
            self.assertNotIn('codex', out.getvalue())
            eza=bindir/'eza'; eza.write_text('#!/bin/sh\nexit 99\n'); eza.chmod(0o755)
            available=io.StringIO()
            dependencies.report(base,base/'live',{'PATH':str(bindir),'XDG_DATA_HOME':str(data)},available)
            self.assertIn('FOUND: eza',available.getvalue())
            with patch.object(dependencies,'report',side_effect=OSError('fixture')):
                with patch.object(sys,'argv',['check_dependencies.py']), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(dependencies.main(),2)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/compare_configs.py'),'--target',tmp],capture_output=True)
            self.assertEqual(result.returncode,1)
            result=subprocess.run([sys.executable,str(ROOT/'scripts/check_dependencies.py')],env={**os.environ,'PATH':''},capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)

if __name__ == '__main__': unittest.main()
