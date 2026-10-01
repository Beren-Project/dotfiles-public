"""Real Zsh startup and PTY checks using only the Python standard library."""
import os
import json
import tomllib
from pathlib import Path
import pty
import select
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

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

    def test_minimal_startup_and_bindings(self):
        code = "print -- $options[sharehistory] $options[incappendhistory]; whence compdef; bindkey '^A'; bindkey '^[[A'; bindkey '^[[13;2u'; print -- ${+functions[TRAPINT]}"
        r=subprocess.run(['zsh','-d','-i','-c',code],env=self.env,cwd=self.home,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(r.stderr,'')
        for expected in ['on off','compdef','beginning-of-line','up-line-or-history','_dotfiles_insert_newline']:
            self.assertIn(expected,r.stdout)
        self.assertTrue(r.stdout.endswith('0\n'))

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
        r = subprocess.run(['zsh','-d','-i','-c',
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
