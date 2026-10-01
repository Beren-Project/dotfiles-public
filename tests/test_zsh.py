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

    def test_wsl_browser_helpers(self):
        bindir = self.home/'bin'; bindir.mkdir()
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
        env = {**self.env, 'WSL_DISTRO_NAME': 'TestUbuntu'}
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
