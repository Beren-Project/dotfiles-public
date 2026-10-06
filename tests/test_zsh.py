"""Real Zsh startup and PTY checks using only the Python standard library."""
import os
import json
import tomllib
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

class TerminalIsolationTests(unittest.TestCase):
    def test_captured_shell_tests_leave_the_controlling_tty_alone(self):
        # Reproduce a terminal-launched/background suite in a PRIVATE PTY.
        # The supervisor owns the foreground group; the test runner must not
        # claim it or read terminal input through its interactive Zsh children.
        names = [
            'test_restore.RestoreTests.test_shell_preview_and_restore_ignore_unmanaged_files',
            'test_zsh.ZshTests.test_completion_initializes_once_and_reuses_cache',
        ]
        for name in names:
            with self.subTest(test=name), tempfile.TemporaryDirectory() as tmp:
                pid, fd = pty.fork()
                if pid == 0:
                    try:
                        env = {'HOME': tmp, 'TMPDIR': tmp, 'PATH': '/usr/bin:/bin',
                               'TERM': 'xterm-256color', 'LANG': 'C.UTF-8',
                               'PYTHONDONTWRITEBYTECODE': '1', 'NO_COLOR': '1'}
                        runner = subprocess.Popen(
                            [sys.executable, '-B', '-m', 'unittest', name, '-v'],
                            cwd=ROOT/'tests', env=env, process_group=0)
                        _, status = os.waitpid(runner.pid, os.WUNTRACED)
                        if os.WIFSTOPPED(status):
                            print('TTY_STOP:' + signal.Signals(os.WSTOPSIG(status)).name, flush=True)
                            os.killpg(runner.pid, signal.SIGKILL)
                            os.waitpid(runner.pid, 0)
                            os._exit(1)
                        if os.tcgetpgrp(0) != os.getpgrp():
                            print('TTY_FOREGROUND_CHANGED', flush=True)
                            os._exit(1)
                        os._exit(os.waitstatus_to_exitcode(status))
                    except BaseException:
                        os._exit(2)
                output = bytearray()
                status = None
                try:
                    deadline = time.monotonic()+15
                    while time.monotonic() < deadline:
                        if select.select([fd], [], [], 0.1)[0]:
                            try:
                                chunk = os.read(fd, 65536)
                            except OSError:
                                chunk = b''
                            # PTY EOF can arrive just before the child is reaped.
                            output.extend(chunk)
                        waited, value = os.waitpid(pid, os.WNOHANG)
                        if waited:
                            status = value
                            break
                    if status is None:
                        waited, value = os.waitpid(pid, os.WNOHANG)
                        if waited: status = value
                    self.assertIsNotNone(status, output.decode(errors='replace'))
                    text = output.decode(errors='replace')
                    self.assertEqual(os.waitstatus_to_exitcode(status), 0, text)
                    self.assertNotIn('\x1b', text, text)  # No prompt escapes leaked to the PTY.
                finally:
                    if status is None:
                        os.kill(pid, signal.SIGKILL)
                        os.waitpid(pid, 0)
                    os.close(fd)

class Shell:
    def __init__(self, home, env):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(home)
            os.execve('/usr/bin/zsh', ['zsh', '-d', '-i'], env)
        self.read()

    def read(self, seconds=0.6):
        output = b''
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            if select.select([self.fd], [], [], max(0,deadline-time.monotonic()))[0]:
                try: output += os.read(self.fd, 65536)
                except OSError: break
        return output.decode(errors='replace')

    def send(self, command):
        os.write(self.fd, command.encode())
        return self.read()

    def close(self):
        os.write(self.fd, b'\x03')
        self.read(0.1)
        os.write(self.fd, b'exit\n')
        self.read(0.2)
        os.close(self.fd)
        import signal
        if os.waitpid(self.pid, os.WNOHANG)[0] == 0:
            os.kill(self.pid, signal.SIGTERM)
            os.waitpid(self.pid, 0)

class ZshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        shutil.copytree(ROOT/'home', self.home, dirs_exist_ok=True)
        self.env = {'HOME':str(self.home),'ZDOTDIR':str(self.home),
                    'XDG_CONFIG_HOME':str(self.home/'.config'),
                    'XDG_DATA_HOME':str(self.home/'.local/share'),
                    'PATH':'/usr/bin:/bin','TERM':'xterm-256color','LANG':'C.UTF-8'}

    def tearDown(self): self.tmp.cleanup()

    def run_zsh(self, command, **kwargs):
        options = {'env': self.env, 'cwd': self.home, 'capture_output': True, 'text': True}
        options.update(kwargs)
        # Captured interactive probes must not inherit stdin OR a controlling
        # TTY. Keep -i (and global startup files) to test the actual shell setup.
        return subprocess.run(command, stdin=subprocess.DEVNULL,
                              start_new_session=True, timeout=10, **options)

    def install_environment_fixtures(self):
        for name in ['.cargo/bin', 'bin', '.local/bin', '.juliaup/bin',
                     '.julia/juliaup/completions']:
            (self.home/name).mkdir(parents=True, exist_ok=True)
        (self.home/'.cargo/env').write_text(
            'CARGO_LOADS=$((${CARGO_LOADS:-0}+1))\n'
            'case ":$PATH:" in *:"$HOME/.cargo/bin":*) ;; '
            '*) export PATH="$HOME/.cargo/bin:$PATH" ;; esac\n')
        for name in ['env', 'env.fish']:
            (self.home/'.local/bin'/name).write_text('echo OBSOLETE_HELPER_SOURCED\n')
        for name in ['zsh.zsh', 'bash.sh']:
            (self.home/'.julia/juliaup/completions'/name).write_text(
                'JULIA_COMPLETION=loaded\n')

    def run_interactive_bash(self, code, env=None):
        result = self.run_zsh(['/bin/bash', '--noprofile', '--norc', '-i', '-c', code],
                              env=self.env if env is None else env)
        self.assertEqual(result.returncode, 0, result.stderr)
        # These captured probes deliberately have no controlling TTY. Check
        # Bash's expected diagnostics without masking errors from our configs.
        stderr = re.sub(r'bash: cannot set terminal process group \(-?\d+\): '
                        r'Inappropriate ioctl for device\n', '', result.stderr)
        stderr = stderr.replace('bash: no job control in this shell\n', '')
        self.assertEqual(stderr, '')
        return result

    def test_complete_path_priority_and_command_ownership(self):
        self.install_environment_fixtures()
        cargo = str(self.home/'.cargo/bin')
        personal = str(self.home/'bin')
        local = str(self.home/'.local/bin')
        nvim = '/opt/nvim-linux-x86_64/bin'
        inherited = ['/usr/bin', '/bin', str(self.home/'inherited Linux tools'),
                     '/mnt/c/Program Files/Useful Tools', '/mnt/c/Windows/System32']
        # Start with misplaced managed entries and duplicate inherited entries.
        entries = [local, inherited[0], personal, cargo, *inherited[1:],
                   cargo, local, inherited[1]]
        if Path(nvim).is_dir():
            entries.append(nvim)
        for directory in [cargo, local]:
            for name in ['cargo', 'uv', 'uvx', 'juliaup', 'julia', 'codex']:
                tool = Path(directory)/name
                tool.write_text('#!/bin/sh\nexit 0\n')
                tool.chmod(0o755)
        # Codex belongs only to generic local-bin availability in this fixture.
        (Path(cargo)/'codex').unlink()
        result = self.run_zsh(['zsh', '-i', '-c',
            'print -r -- "$PATH"; source ~/.zshenv; source ~/.zshrc; '
            'print -r -- "$PATH"; '
            'for tool in cargo uv uvx juliaup julia codex; do whence -p "$tool"; done; '
            'print -r -- "$JULIA_COMPLETION"'],
            env={**self.env, 'PATH': ':'.join(entries)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        expected = ([nvim] if Path(nvim).is_dir() else []) + [cargo, *inherited, personal, local]
        self.assertEqual(result.stdout.splitlines(), [':'.join(expected)] * 2 +
                         [str(Path(cargo)/name) for name in ['cargo', 'uv', 'uvx', 'juliaup', 'julia']] +
                         [str(Path(local)/'codex'), 'loaded'])

    def test_noninteractive_zsh_owns_base_environment(self):
        self.install_environment_fixtures()
        result = self.run_zsh(['zsh', '-c', 'print -r -- "$PATH"; print -- $CARGO_LOADS'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.stdout.splitlines(), [
            f'{self.home}/.cargo/bin:/usr/bin:/bin:{self.home}/bin:{self.home}/.local/bin', '1'])
        self.assertFalse((self.home/'.zcompdump').exists())

    def test_interactive_comments_in_copied_commands(self):
        result = self.run_zsh(['zsh', '-i', '-c',
            '# Copied comment\nprint -- COMMENT_BLOCK_OK # trailing comment\n'
            'print -- $options[interactivecomments]'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.stdout, 'COMMENT_BLOCK_OK\non\n')

    def install_fnm_fixture(self, fail=False):
        self.install_environment_fixtures()
        log = self.home/'fnm.jsonl'
        fnm = self.home/'.cargo/bin/fnm'
        fnm.write_text('#!/usr/bin/python3\nimport json, os, pathlib, shlex, sys\n'
            f'log = pathlib.Path({str(log)!r})\n'
            'with log.open("a") as stream:\n'
            '    stream.write(json.dumps({"args": sys.argv[1:], "path": os.environ["PATH"]}) + "\\n")\n'
            + ('print(\'export PATH="/failed-output-must-not-be-applied"\')\nsys.exit(7)\n' if fail else
               'multishell = str(log.parent/"runtime/fnm_multishells"/str(os.getpid()))\n'
               'print("export FNM_MULTISHELL_PATH=" + shlex.quote(multishell))\n'
               'print("export PATH=" + shlex.quote(multishell + "/bin") + ":$PATH")\n'))
        fnm.chmod(0o755)
        return log

    def test_fnm_repeated_and_nested_startup_removes_only_multishell_paths(self):
        log = self.install_fnm_fixture()
        stale = ['/run/user/1000/fnm_multishells/old/bin',
                 str(self.home/'runtime/fnm_multishells/older/bin')]
        unrelated = ['/opt/fnm_multishells-tools/personal/bin',
                     '/opt/fnm_multishells/personal/nested/bin',
                     'fnm_multishells/personal/bin', '/mnt/c/Windows/System32']
        env = {**self.env, 'PATH': ':'.join([*stale, '/usr/bin', '/bin', *unrelated])}
        result = self.run_zsh(['zsh', '-i', '-c',
            'print -r -- "$PATH"; source ~/.zshrc; print -r -- "$PATH"; '
            'zsh -i -c \'print -r -- "$PATH"\''], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        paths = [line.split(':') for line in result.stdout.splitlines()]
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(paths), 3)
        expected_tail = (['/opt/nvim-linux-x86_64/bin']
                         if Path('/opt/nvim-linux-x86_64/bin').is_dir() else [])
        expected_tail += [str(self.home/'.cargo/bin'), '/usr/bin', '/bin',
                          *unrelated, str(self.home/'bin'), str(self.home/'.local/bin')]
        for call, entries in zip(calls, paths):
            self.assertEqual(call['args'], ['env', '--use-on-cd', '--shell', 'zsh'])
            self.assertTrue(entries[0].startswith(str(self.home/'runtime/fnm_multishells') + '/'))
            self.assertTrue(entries[0].endswith('/bin'))
            self.assertEqual(entries[1:], expected_tail)
        self.assertEqual(len({entries[0] for entries in paths}), 3)
        # Generation sees the prior entries before cleanup starts.
        self.assertTrue(set(stale).issubset(calls[0]['path'].split(':')))
        self.assertIn(paths[0][0], calls[1]['path'].split(':'))
        self.assertIn(paths[1][0], calls[2]['path'].split(':'))

    def test_fnm_generation_failure_preserves_exact_path(self):
        log = self.install_fnm_fixture(fail=True)
        env = {**self.env, 'PATH': ':'.join([
            '/run/user/1000/fnm_multishells/old/bin', '/usr/bin', '/bin',
            '/mnt/c/Program Files/Useful Tools', '/run/user/1000/fnm_multishells/older/bin'])}
        result = self.run_zsh(['zsh', '-i', '-c',
            'print -r -- "$PATH"; source ~/.zshrc; print -r -- "$PATH"'], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        # Compare the exact PATH at generation time, not just its membership.
        self.assertEqual(result.stdout.splitlines(), [call['path'] for call in calls])
        self.assertEqual(calls[0]['path'], calls[1]['path'])

    def test_portable_profile_priority_and_repeated_sourcing(self):
        self.install_environment_fixtures()
        inherited = ['/usr/bin', '/bin', '/mnt/c/Program Files/Useful Tools',
                     '/mnt/c/Windows/System32']
        cargo, personal, local = [str(self.home/name) for name in ['.cargo/bin', 'bin', '.local/bin']]
        # Leading, trailing, and consecutive empty entries must all disappear.
        env = {**self.env, 'PATH': ':'.join([
            '', local, *inherited[:3], '', '', inherited[3], personal, cargo, '/usr/bin', local, ''])}
        result = self.run_zsh(['/bin/sh', '-c',
            '. "$HOME/.profile"; printf "%s\\n" "$PATH"; '
            '. "$HOME/.profile"; printf "%s\\n" "$PATH"'], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.stdout.splitlines(), [':'.join([cargo, *inherited, personal, local])] * 2)
        for normalized in result.stdout.splitlines():
            self.assertNotIn('', normalized.split(':'))

    def test_portable_profile_does_not_reintroduce_empty_components(self):
        self.install_environment_fixtures()
        for available in ['cargo environment', 'cargo directory', 'personal directories', 'local directory']:
            with self.subTest(available=available):
                if available == 'cargo directory':
                    (self.home/'.cargo/env').unlink()
                elif available == 'personal directories':
                    (self.home/'.cargo/bin').rmdir()
                elif available == 'local directory':
                    (self.home/'bin').rmdir()
                result = self.run_zsh(['/bin/sh', '-c',
                    '. "$HOME/.profile"; printf "%s\\n" "$PATH"; '
                    '. "$HOME/.profile"; printf "%s\\n" "$PATH"'],
                    env={**self.env, 'PATH': '::'})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                expected = ':'.join(str(self.home/name) for name in ['.cargo/bin', 'bin', '.local/bin']
                                    if (self.home/name).is_dir())
                self.assertEqual(result.stdout.splitlines(), [expected] * 2)
                for normalized in result.stdout.splitlines():
                    self.assertNotIn('', normalized.split(':'))

    def test_bash_login_environment_loads_cargo_once_before_interactive_setup(self):
        self.install_environment_fixtures()
        result = self.run_interactive_bash(
            '. "$HOME/.profile"; printf "%s\\n" "$PATH" "$CARGO_LOADS" "$JULIA_COMPLETION"')
        self.assertEqual(result.stdout.splitlines(), [
            f'{self.home}/.cargo/bin:/usr/bin:/bin:{self.home}/bin:{self.home}/.local/bin', '1', 'loaded'])

    def test_bash_fallback_fills_missing_entries_without_reordering_present_entries(self):
        self.install_environment_fixtures()
        code = '. "$HOME/.bashrc"; . "$HOME/.bashrc"; printf "%s\\n" "$PATH" "${CARGO_LOADS:-0}"'
        cargo, local = [str(self.home/name) for name in ['.cargo/bin', '.local/bin']]
        inherited = ['/usr/bin', '/bin', '/mnt/c/Windows/System32']
        for entries, expected, loads in [
            (inherited, [cargo, *inherited, local], '1'),
            ([local, *inherited, cargo], [local, *inherited, cargo], '0'),
        ]:
            with self.subTest(entries=entries):
                result = self.run_interactive_bash(code, env={**self.env, 'PATH': ':'.join(entries)})
                self.assertEqual(result.stdout.splitlines(), [':'.join(expected), loads])

    def test_startup_without_generated_cargo_environment(self):
        for directories_present in [False, True]:
            with self.subTest(directories_present=directories_present):
                if directories_present:
                    self.install_environment_fixtures()
                    (self.home/'.cargo/env').unlink()
                cargo = [str(self.home/'.cargo/bin')] if directories_present else []
                local = [str(self.home/'.local/bin')] if directories_present else []
                personal = [str(self.home/'bin')] if directories_present else []
                expected = ':'.join([*cargo, '/usr/bin', '/bin', *personal, *local])
                for command in [['zsh', '-c', 'print -r -- "$PATH"'],
                                ['/bin/sh', '-c', '. "$HOME/.profile"; printf "%s\\n" "$PATH"']]:
                    result = self.run_zsh(command)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, '')
                    self.assertEqual(result.stdout.strip(), expected)
                result = self.run_interactive_bash('. "$HOME/.bashrc"; printf "%s\\n" "$PATH"')
                self.assertEqual(result.stdout.strip(), ':'.join([*cargo, '/usr/bin', '/bin', *local]))

    def profile_startup(self):
        # Include /etc/zsh/zshrc: -d would hide Ubuntu's duplicate compinit.
        result = self.run_zsh(['zsh', '-i', '-c',
            'print -- CUSTOM:${_comps[probe]} EXTRA:${_comps[extra]}; zprof'],
            env=self.env, cwd=self.home, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        rows = result.stdout.split('-----------------------------------------------------------------------------------')[1]
        counts = {match[2]: int(match[1]) for match in re.findall(
            r'^\s*(\d+)\)\s+(\d+)\s+.*?\s+(\w+)\s*$', rows, re.MULTILINE)}
        return result.stdout, counts

    def test_completion_initializes_once_and_reuses_cache(self):
        config = self.home/'.zshenv'
        config.write_text('zmodload zsh/zprof\n' + config.read_text())
        custom = self.home/'.zfunc'; custom.mkdir()
        (custom/'_probe').write_text('#compdef probe\n_arguments "1:target:(alpha beta)"\n')
        output, counts = self.profile_startup()
        self.assertIn('CUSTOM:_probe', output)
        self.assertEqual(counts.get('compinit', 0), 1)
        self.assertEqual(counts.get('compdump', 0), 1)
        dump = self.home/'.zcompdump'
        original = (dump.read_bytes(), dump.stat().st_mtime_ns)
        _, counts = self.profile_startup()
        self.assertEqual(counts.get('compinit', 0), 1)
        self.assertGreater(counts.get('compaudit', 0), 0)
        self.assertEqual(counts.get('compdump', 0), 0)
        self.assertEqual((dump.read_bytes(), dump.stat().st_mtime_ns), original)
        (custom/'_extra').write_text('#compdef extra\n_arguments "1:target:(gamma)"\n')
        output, counts = self.profile_startup()
        self.assertIn('EXTRA:_extra', output)
        self.assertEqual(counts.get('compinit', 0), 1)
        self.assertEqual(counts.get('compdump', 0), 1)

    def test_insecure_completion_directory_is_ignored(self):
        custom = self.home/'.zfunc'; custom.mkdir(mode=0o777)
        custom.chmod(0o777)
        (custom/'_probe').write_text('#compdef probe\nprint UNTRUSTED_COMPLETION\n')
        result = self.run_zsh(['zsh', '-i', '-c', 'print -- REGISTERED:${+_comps[probe]}'],
            env=self.env, cwd=self.home, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.stdout, 'REGISTERED:0\n')

    def test_completion_directory_colors_and_selection(self):
        for name in ['folder-alpha', 'folder-beta']:
            (self.home/name).mkdir()
        shell = Shell(self.home, self.env)
        try:
            output = shell.send('cd folder-\t\t')
            self.assertIn('folder-alpha', output)
            self.assertIn('folder-beta', output)
            # Check a foreground color on the actual directory listing,
            # independently of prompt colors or selection reverse video.
            self.assertIn('\x1b[1;34mfolder-alpha', output)
            self.assertRegex(output, r'\x1b\[(?:[0-9]+;)*7m')
            shell.send('\t')
            shell.send('\n')  # Accept the menu selection into the command line.
            shell.send('\n')  # Execute cd.
            output = shell.send('print -- SELECTED:${PWD:t}\n')
            self.assertIn('SELECTED:folder-beta', output)
            shell.send('cd ..\n')
            for name in ['palette-plain', 'palette-code.py', 'palette-image.png', 'palette-archive.zip']:
                (self.home/name).touch()
            output = shell.send('print palette-\t\t')
            for color, name in [('1;33', 'palette-code.py'), ('35', 'palette-image.png'),
                                ('31', 'palette-archive.zip')]:
                self.assertIn(f'\x1b[{color}m{name}', output)
        finally:
            shell.close()

    def test_optional_tools_and_inherited_path(self):
        bindir = self.home/'bin'; bindir.mkdir()
        for name in ['fnm', 'direnv', 'zoxide']:
            tool = bindir/name
            tool.write_text(f'#!/bin/sh\nprintf "typeset -g PROBE_{name}=loaded\\n"\n')
            tool.chmod(0o755)
        eza = bindir/'eza'
        eza.write_text('#!/bin/sh\nprintf "EZA_ARGS:%s\\n" "$*"\n')
        eza.chmod(0o755)
        env = {**self.env, 'PATH': self.env['PATH'] + ':/mnt/c/Windows/System32'}
        result = self.run_zsh(['zsh', '-i', '-c',
            'print -- $PROBE_fnm $PROBE_direnv $PROBE_zoxide; print -l -- $path; ls; la'],
            env=env, cwd=self.home, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('loaded loaded loaded\n', result.stdout)
        self.assertIn('/mnt/c/Windows/System32\n', result.stdout)
        self.assertIn('EZA_ARGS:\n', result.stdout)
        self.assertIn('EZA_ARGS:-la\n', result.stdout)

    def test_minimal_startup_and_bindings(self):
        code = "print -- $options[sharehistory] $options[incappendhistory]; whence compdef; bindkey '^A'; bindkey '^[[A'; bindkey '^[[13;2u'; print -- ${+functions[TRAPINT]}"
        r=self.run_zsh(['zsh','-d','-i','-c',code],env=self.env,cwd=self.home,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(r.stderr,'')
        for expected in ['on off','compdef','beginning-of-line','up-line-or-history','_dotfiles_insert_newline']:
            self.assertIn(expected,r.stdout)
        self.assertTrue(r.stdout.endswith('0\n'))

    def install_fzf_fixture(self, script, status=0, diagnostic=''):
        bindir = self.home/'fzf-tools'
        bindir.mkdir()
        log = self.home/'fzf-calls.jsonl'
        tool = bindir/'fzf'
        tool.write_text('#!/usr/bin/python3\nimport json, pathlib, sys\n'
            f'with pathlib.Path({str(log)!r}).open("a") as stream:\n'
            '    stream.write(json.dumps(sys.argv[1:]) + "\\n")\n'
            f'sys.stdout.write({script!r})\n'
            f'sys.stderr.write({diagnostic!r})\n'
            f'sys.exit({status})\n')
        tool.chmod(0o755)
        self.env['PATH'] = str(bindir) + ':' + self.env['PATH']
        return log

    def run_pty_zsh(self, code, options=('-l', '-i')):
        # A finite startup probe with real terminal stdin; stderr shares the
        # private PTY so diagnostics cannot disappear into an unobserved stream.
        command = ['/usr/bin/zsh', *options, '-c', code]
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(self.home)
            os.execve(command[0], command, self.env)
        output = bytearray()
        status = None
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(fd, 65536)
                    except OSError:
                        chunk = b''
                    output.extend(chunk)
                waited, value = os.waitpid(pid, os.WNOHANG)
                if waited:
                    status = value
                    # Drain bytes written immediately before the child exited.
                    while select.select([fd], [], [], 0)[0]:
                        try:
                            chunk = os.read(fd, 65536)
                        except OSError:
                            break
                        if not chunk:
                            break
                        output.extend(chunk)
                    break
            self.assertIsNotNone(status, output.decode(errors='replace'))
            return subprocess.CompletedProcess(command, os.waitstatus_to_exitcode(status),
                                               output.decode(errors='replace').replace('\r\n', '\n'))
        finally:
            if status is None:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            os.close(fd)

    def fzf_probe(self):
        return ("print -- WIDGETS:${+widgets[fzf-history-widget]}:"
                "${+widgets[fzf-file-widget]}:${+widgets[fzf-cd-widget]}:"
                "${+widgets[fzf-completion]}; "
                "bindkey '^R'; bindkey '^T'; bindkey '^[c'; bindkey '^I'; "
                "print -- TEMP:${+_dotfiles_fzf_env}; "
                "print -- LATER:${+widgets[_dotfiles_insert_newline]}; true")

    def assert_native_fzf_bindings(self, output):
        self.assertIn('WIDGETS:0:0:0:0\n', output)
        for binding in ['"^R" history-incremental-search-backward',
                        '"^T" transpose-chars', '"^[c" capitalize-word',
                        '"^I" expand-or-complete']:
            self.assertIn(binding + '\n', output)
        self.assertIn('TEMP:0\n', output)
        self.assertIn('LATER:1\n', output)

    def test_fzf_binary_output_installs_widgets_and_bindings(self):
        # Identifiable functions prove these widgets came from --zsh output,
        # even when this machine happens to have the distro example files.
        script = ''
        for widget, key in [('history', '^R'), ('file', '^T'), ('cd', '^[c')]:
            name = f'fzf-{widget}-widget'
            script += (f'{name}() {{ print -- FIXTURE_{widget}; }}\n'
                       f'zle -N {name}\nbindkey "{key}" {name}\n')
        script += ('fzf-completion() { print -- FIXTURE_completion; }\n'
                   "zle -N fzf-completion\nbindkey '^I' fzf-completion\n")
        log = self.install_fzf_fixture(script)
        result = self.run_pty_zsh(self.fzf_probe() +
            '; fzf-history-widget; fzf-file-widget; fzf-cd-widget; fzf-completion')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, 'WIDGETS:1:1:1:1\n'
            '"^R" fzf-history-widget\n"^T" fzf-file-widget\n'
            '"^[c" fzf-cd-widget\n"^I" fzf-completion\nTEMP:0\nLATER:1\n'
            'FIXTURE_history\nFIXTURE_file\nFIXTURE_cd\nFIXTURE_completion\n')
        self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], [['--zsh']])

    def test_fzf_generation_failure_discards_output_and_preserves_diagnostic(self):
        log = self.install_fzf_fixture(
            'typeset -g FZF_PARTIAL_APPLIED=1\nbindkey "^R" undefined-partial-widget\n',
            status=7, diagnostic='FZF_GENERATOR_FAILURE\n')
        result = self.run_pty_zsh(self.fzf_probe() + '; print -- PARTIAL:${+FZF_PARTIAL_APPLIED}')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assert_native_fzf_bindings(result.stdout)
        self.assertIn('FZF_GENERATOR_FAILURE\n', result.stdout)
        self.assertIn('PARTIAL:0\n', result.stdout)
        self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], [['--zsh']])

    def test_fzf_evaluation_failure_is_visible_and_startup_continues(self):
        self.install_fzf_fixture('command _dotfiles_fzf_missing_runtime_command\n')
        result = self.run_pty_zsh(self.fzf_probe())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assert_native_fzf_bindings(result.stdout)
        self.assertIn('command not found: _dotfiles_fzf_missing_runtime_command\n', result.stdout)

    def test_fzf_absent_leaves_native_widgets_and_clean_startup(self):
        bindir = self.home/'without-fzf'
        bindir.mkdir()
        for name in ['mkdir', 'mv', 'rm', 'cat', 'date', 'hostname', 'uname']:
            location = shutil.which(name, path='/usr/bin:/bin')
            if location:
                (bindir/name).symlink_to(location)
        self.env['PATH'] = str(bindir)
        result = self.run_pty_zsh('command -v fzf >/dev/null 2>&1; '
                                 'print -- FZF_LOOKUP:$?; ' + self.fzf_probe())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(result.stdout.startswith('FZF_LOOKUP:1\n'), result.stdout)
        self.assert_native_fzf_bindings(result.stdout)
        clean = self.run_pty_zsh('true')
        self.assertEqual(clean.returncode, 0, clean.stdout)
        self.assertEqual(clean.stdout, '')

    def test_fzf_generator_obeys_interactive_zle_and_stdin_guards(self):
        log = self.install_fzf_fixture('print -u2 -- UNEXPECTED_FZF_LOAD\n')
        # Source explicitly to exercise the interactive-only early return.
        noninteractive = self.run_pty_zsh('source "$ZDOTDIR/.zshrc"; true', options=('-l',))
        self.assertEqual(noninteractive.returncode, 0, noninteractive.stdout)
        self.assertEqual(noninteractive.stdout, '')
        nonterminal = self.run_zsh(['/usr/bin/zsh', '-lic', 'true'])
        self.assertEqual(nonterminal.returncode, 0, nonterminal.stderr)
        self.assertEqual(nonterminal.stdout, '')
        self.assertEqual(nonterminal.stderr, '')
        no_zle = self.run_pty_zsh('print -- ZLE:$options[zle]; ' + self.fzf_probe(),
                                  options=('-l', '-i', '+o', 'zle'))
        self.assertEqual(no_zle.returncode, 0, no_zle.stdout)
        self.assertTrue(no_zle.stdout.startswith('ZLE:off\n'), no_zle.stdout)
        self.assert_native_fzf_bindings(no_zle.stdout)
        self.assertFalse(log.exists())

    def test_wsl_browser_helpers(self):
        # Conversion fixtures must be ahead of the real system wslpath;
        # ~/bin now intentionally follows inherited system directories.
        bindir = self.home/'browser-tools'; bindir.mkdir()
        log = self.home/'browser.jsonl'
        converter = bindir/'wslpath'
        converter.write_text('#!/usr/bin/python3\nimport sys\n'
            'if "conversion-fails" in sys.argv[2]: sys.exit(7)\n'
            'print("WIN:" + sys.argv[2])\n')
        converter.chmod(0o755)
        for browser in ['msedge', 'chrome']:
            executable = bindir/(browser + '.exe')
            executable.write_text('#!/usr/bin/python3\nimport sys,json\n'
                + f'with open({str(log)!r}, "a") as f: f.write(json.dumps(sys.argv) + "\\n")\n')
            executable.chmod(0o755)
        env = {**self.env, 'WSL_DISTRO_NAME': 'TestUbuntu',
               'PATH': str(bindir) + ':' + self.env['PATH']}
        for browser in ['edge', 'chrome']:
            for filename in ['notes with spaces.md', '-notes.md', 'notes %TEMP% & !.txt']:
                with self.subTest(browser=browser, filename=filename):
                    target = self.home/filename; target.touch()
                    before = len(log.read_text().splitlines()) if log.exists() else 0
                    result = self.run_zsh(['zsh', '-d', '-i', '-c',
                        f'{browser} "$1"; result=$?; print -r -- "$PWD"; exit $result',
                        'test', filename], env=env, cwd=self.home, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, str(self.home) + '\n')
                    self.assertEqual(result.stderr, '')
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        entries = log.read_text().splitlines() if log.exists() else []
                        if len(entries) > before: break
                        time.sleep(0.01)
                    self.assertEqual(len(entries), before + 1)
                    argv = json.loads(entries[-1])
                    self.assertEqual(Path(argv[0]).name, ('msedge' if browser == 'edge' else browser) + '.exe')
                    self.assertEqual(argv[1:], ['WIN:' + str(target)])
        original = log.read_bytes()
        (self.home/'conversion-fails').touch()
        for browser in ['edge', 'chrome']:
            for args in [[], ['missing.md'], ['.'], ['conversion-fails'], ['one', 'two']]:
                with self.subTest(browser=browser, args=args):
                    result = self.run_zsh(['zsh', '-d', '-i', '-c', f'{browser} "$@"', 'test', *args],
                        env=env, cwd=self.home, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(log.read_bytes(), original)
        result = self.run_zsh(['zsh', '-d', '-i', '-c',
            'print -- ${+functions[edge]} ${+functions[chrome]}'],
            env=self.env, cwd=self.home, capture_output=True, text=True)
        self.assertEqual(result.stdout, '0 0\n')

    def test_starship_pty_status_and_input(self):
        starship=shutil.which('starship')
        if not starship: self.skipTest('Starship not installed')
        bindir=self.home/'bin'; bindir.mkdir()
        # Log transient calls while leaving Starship's generated init untouched.
        wrapper=bindir/'starship'
        wrapper.write_text('#!/usr/bin/python3\nimport os, sys, json\n'
            + 'with open(' + repr(str(self.home/'starship-calls.jsonl')) + ', "a") as log:\n'
            + '    log.write(json.dumps(sys.argv[1:]) + "\\n")\n'
            + 'os.execv(' + repr(starship) + ', [' + repr(starship) + '] + sys.argv[1:])\n')
        wrapper.chmod(0o755)
        shell=Shell(self.home,self.env)
        try:
            output=shell.send('false\n')
            self.assertIn('',output)
            output=shell.send("printf 'RESULT:%s:%s\\n' failure $?\n")
            self.assertIn('RESULT:failure:1',output)
            shell.send('true\n')
            output=shell.send("printf 'RESULT:%s:%s\\n' success $?\n")
            self.assertIn('RESULT:success:0',output)
            output=shell.send("printf 'RESULT:%s\\n' full_prompt\n")
            self.assertIn('', output.partition('\r\nRESULT:full_prompt\r\n')[2])
            shell.send('\n')
            shell.send('not-executed\x03')
            output=shell.send("printf 'RESULT:%s\\n' cancel_ok\n")
            self.assertIn('RESULT:cancel_ok',output)
            shell.send('sleep 10\n')
            shell.send('\x03')
            output=shell.send("printf 'RESULT:%s:%s\\n' interrupted $?\n")
            self.assertIn('RESULT:interrupted:130',output)
            output=shell.send("printf 'RESULT:%s\\n' first\x1b[13;2uprintf 'RESULT:%s\\n' second\n")
            self.assertIn('RESULT:first',output); self.assertIn('RESULT:second',output)
            calls=[json.loads(line) for line in (self.home/'starship-calls.jsonl').read_text().splitlines()]
            transient_calls=[args for args in calls if '--profile' in args and 'transient' in args]
            self.assertTrue(transient_calls)
            for args in transient_calls:
                self.assertFalse(any(arg.startswith(('--status', '--cmd-duration')) for arg in args))
            self.assertNotIn('No such widget',output)
        finally: shell.close()

    def test_transient_redraw_removes_full_prompt(self):
        starship = shutil.which('starship')
        if not starship:
            self.skipTest('Starship not installed')
        bindir = self.home/'bin'; bindir.mkdir()
        (bindir/'starship').symlink_to(starship)
        plugin_source = os.environ.get('DOTFILES_TEST_PLUGINS')
        if plugin_source:
            shutil.copytree(plugin_source, self.home/'.local/share/zsh/plugins')
        shell = Shell(self.home, self.env)
        try:
            for _ in range(2):
                output = shell.send("printf 'TRANSIENT_%s\\n' RESULT\n")
                before, separator, after = output.partition('\r\nTRANSIENT_RESULT\r\n')
                self.assertTrue(separator, repr(output))
                # Inspect the actual redraw before execution, not just hook calls.
                self.assertIn('\x1b[J', before)
                redraw = before.split('\x1b[J', 1)[1]
                self.assertIn('', redraw)
                self.assertNotIn('', redraw)  # Full prompt's colored opening segment.
                self.assertIn('', after)     # Next full prompt restored.
        finally:
            shell.close()

    def test_arrow_colors_are_status_independent(self):
        starship=shutil.which('starship')
        if not starship: self.skipTest('Starship not installed')
        config=self.home/'.config/starship.toml'
        tomllib.loads(config.read_text())
        env={**self.env, 'STARSHIP_CONFIG':str(config), 'STARSHIP_SHELL':'zsh'}
        for keymap in ['emacs','viins','vicmd','replace_one','replace','visual']:
            outputs=[]
            for status in ['0','1','130']:
                result=subprocess.run([starship,'prompt','--profile','transient',
                    '--status',status,'--keymap',keymap],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stderr,'')
                outputs.append(result.stdout)
            self.assertEqual(outputs[0],outputs[1])
            self.assertEqual(outputs[0],outputs[2])
            self.assertIn('38;2;152;151;26',outputs[0])  # Existing green palette.
            character=subprocess.run([starship,'module','character','--status','1',
                '--keymap',keymap],env=env,capture_output=True,text=True)
            self.assertEqual(character.returncode,0,character.stderr)
            self.assertEqual(character.stdout.strip(),
                outputs[0].replace('%{','').replace('%}','').strip())

    def test_standalone_plugins(self):
        plugin_source = os.environ.get('DOTFILES_TEST_PLUGINS')
        if not plugin_source:
            self.skipTest('Set DOTFILES_TEST_PLUGINS to an installed pinned plugin directory')
        shutil.copytree(plugin_source, self.home/'.local/share/zsh/plugins')
        r = self.run_zsh(['zsh','-d','-i','-c',
            "print -- ${+widgets[history-substring-search-up]} ${+functions[_zsh_autosuggest_start]} ${+functions[_zsh_highlight]}; bindkey '^[[A'"],
            env=self.env, cwd=self.home, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, '')
        self.assertIn('1 1 1', r.stdout)
        self.assertIn('history-substring-search-up', r.stdout)
        shell = Shell(self.home, self.env)
        try:
            shell.send('print -- PLUGIN_MARKER\n')
            output = shell.send('print -- PLUG')
            self.assertIn('IN_MARKER', output)  # Autosuggestion displayed.
            output = shell.send('\x03')
            shell.send('PLUGIN_')
            output = shell.send('\x1b[A\n')
            self.assertIn('PLUGIN_MARKER', output)
            output = shell.send('print -- HIGHLIGHT_OK\n')
            self.assertIn('HIGHLIGHT_OK', output)
            self.assertNotIn('No such widget', output)
        finally:
            shell.close()

    def test_shared_history_and_completion(self):
        (self.home/'completion-target').touch()
        one=Shell(self.home,self.env); two=Shell(self.home,self.env)
        try:
            one.send('print -- SHARED_MARKER\n')
            two.send('\n')
            output=two.send('fc -l -20\n')
            self.assertIn('SHARED_MARKER',output)
            output=one.send('print -- completion-t\t\n')
            self.assertIn('completion-target',output)
        finally: one.close(); two.close()

if __name__ == '__main__': unittest.main()
