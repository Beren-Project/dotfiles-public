"""Exercise restoration against disposable homes; never touch the live home."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class RestoreTests(unittest.TestCase):
    def run_restore(self, target, apply=False):
        return subprocess.run([sys.executable, str(ROOT/'scripts/restore.py'),
                               '--target', str(target)] + (['--apply'] if apply else []),
                              capture_output=True, text=True)

    def test_preview_restore_backup_and_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'new-home'
            self.assertEqual(self.run_restore(target).returncode, 0)
            self.assertFalse(target.exists())
            target.mkdir()
            (target/'.zshrc').write_text('old config')
            result = self.run_restore(target, True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for src in (ROOT/'home').rglob('*'):
                if src.is_file():
                    self.assertEqual(src.read_bytes(), (target/src.relative_to(ROOT/'home')).read_bytes())
            backups = list((target/'.dotfiles-backups').glob('*/.zshrc'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), 'old config')
            self.assertEqual(self.run_restore(target, True).returncode, 0)
            self.assertEqual(len(list((target/'.dotfiles-backups').iterdir())), 1)

    def test_conflicts_fail_before_copying(self):
        for conflict in ['parent-link', 'backup-link', 'directory', 'parent-file']:
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)/'home'; target.mkdir()
                outside = Path(tmp)/'outside'; outside.mkdir()
                if conflict == 'parent-link': (target/'.config').symlink_to(outside)
                elif conflict == 'backup-link': (target/'.dotfiles-backups').symlink_to(outside)
                elif conflict == 'directory': (target/'.zshrc').mkdir()
                else: (target/'.config').write_text('not a directory')
                self.assertNotEqual(self.run_restore(target, True).returncode, 0)
                self.assertFalse((target/'.bashrc').exists())
                self.assertEqual(list(outside.iterdir()), [])

    def test_existing_file_symlink_is_preserved_in_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'home'; target.mkdir()
            original = Path(tmp)/'original'; original.write_text('keep me')
            (target/'.zshrc').symlink_to(original)
            self.assertEqual(self.run_restore(target, True).returncode, 0)
            self.assertEqual(original.read_text(), 'keep me')
            self.assertTrue(next((target/'.dotfiles-backups').glob('*/.zshrc')).is_symlink())

    def test_repository_inside_default_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            repo = target/'project/dotfiles'
            shutil.copytree(ROOT/'home', repo/'home')
            (repo/'scripts').mkdir()
            shutil.copy2(ROOT/'scripts/restore.py', repo/'scripts/restore.py')
            shutil.copy2(ROOT/'managed-files.txt', repo/'managed-files.txt')
            before = {p.relative_to(repo): p.read_bytes() for p in repo.rglob('*') if p.is_file()}
            (target/'.zshrc').write_text('old config')
            command = [sys.executable, str(repo/'scripts/restore.py')]
            env = {**os.environ, 'HOME': str(target)}
            preview = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual((target/'.zshrc').read_text(), 'old config')
            self.assertFalse((target/'.dotfiles-backups').exists())
            result = subprocess.run(command+['--apply'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((target/'.zshrc').read_bytes(), (repo/'home/.zshrc').read_bytes())
            self.assertEqual(next((target/'.dotfiles-backups').glob('*/.zshrc')).read_text(), 'old config')
            self.assertEqual(before, {p.relative_to(repo): p.read_bytes() for p in repo.rglob('*') if p.is_file()})

    def test_destination_inside_repository_rejected_before_copying(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            repo = target/'.config/mermaid'
            (repo/'scripts').mkdir(parents=True)
            shutil.copy2(ROOT/'scripts/restore.py', repo/'scripts/restore.py')
            shutil.copy2(ROOT/'managed-files.txt', repo/'managed-files.txt')
            shutil.copytree(ROOT/'home', repo/'home')
            result = subprocess.run([sys.executable, str(repo/'scripts/restore.py'),
                '--target', str(target), '--apply'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((target/'.bashrc').exists())
            self.assertFalse((repo/'pptr.json').exists())

    def test_shell_preview_and_restore_ignore_unmanaged_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); repo = base/'repo'; user = base/'user'; user.mkdir()
            shutil.copytree(ROOT/'home', repo/'home')
            (repo/'scripts').mkdir()
            for script in ['restore.py', 'preview_zsh.py', 'compare_configs.py']:
                shutil.copy2(ROOT/'scripts'/script, repo/'scripts'/script)
            shutil.copy2(ROOT/'managed-files.txt', repo/'managed-files.txt')
            before = {p.relative_to(repo/'home'):p.read_bytes() for p in (repo/'home').rglob('*') if p.is_file()}
            env = {'HOME':str(user), 'PATH':'/usr/bin:/bin', 'TERM':'xterm-256color', 'LANG':'C.UTF-8'}
            preview = subprocess.run([sys.executable, str(repo/'scripts/preview_zsh.py')],
                input='print -r -- "PREVIEW_DUMP:$_comp_dumpfile"\nexit\n', env=env,
                # A pipe alone does not stop interactive Zsh opening /dev/tty.
                start_new_session=True, capture_output=True, text=True, timeout=10)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            dump_line = next(line for line in preview.stdout.splitlines() if line.startswith('PREVIEW_DUMP:'))
            dump = Path(dump_line.split(':',1)[1])
            self.assertNotEqual(dump.parent, repo/'home')
            self.assertFalse(dump.parent.exists())  # Temporary preview cleaned up.
            self.assertEqual(before, {p.relative_to(repo/'home'):p.read_bytes() for p in (repo/'home').rglob('*') if p.is_file()})
            # Simulate leftovers from older previews and unrelated local data.
            for name in ['.zcompdump', '.zcompdump.zwc', '.private-note', '.gitconfig.local']:
                (repo/'home'/name).write_text('must not restore')
            result = subprocess.run([sys.executable, str(repo/'scripts/restore.py'),
                '--target', str(user), '--apply'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('9 files.', result.stdout)
            for name in ['.zcompdump', '.zcompdump.zwc', '.private-note', '.gitconfig.local']:
                self.assertFalse((user/name).exists())
            report = subprocess.run([sys.executable, str(repo/'scripts/compare_configs.py'),
                '--target', str(user)], capture_output=True, text=True)
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn('IDENTICAL=9', report.stdout)

    def test_missing_or_symlinked_managed_source_fails_before_restore(self):
        for mode in ['missing', 'parent-symlink']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp);repo=base/'repo';target=base/'target'
                shutil.copytree(ROOT/'home',repo/'home');(repo/'scripts').mkdir()
                shutil.copy2(ROOT/'scripts/restore.py',repo/'scripts/restore.py')
                shutil.copy2(ROOT/'managed-files.txt',repo/'managed-files.txt')
                if mode == 'missing':
                    (repo/'home/.zshrc').unlink()
                else:
                    (repo/'home/.config').rename(base/'config')
                    (repo/'home/.config').symlink_to(base/'config')
                result=subprocess.run([sys.executable,str(repo/'scripts/restore.py'),
                    '--target',str(target),'--apply'],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(target.exists())

    def test_repository_overlap_rejected(self):
        self.assertNotEqual(self.run_restore(ROOT/'home', True).returncode, 0)

class SelectiveRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base/'repo'
        self.target = self.base/'target'
        shutil.copytree(ROOT/'home', self.repo/'home')
        (self.repo/'scripts').mkdir()
        shutil.copy2(ROOT/'scripts/restore.py', self.repo/'scripts/restore.py')
        shutil.copy2(ROOT/'managed-files.txt', self.repo/'managed-files.txt')
        self.names = (self.repo/'managed-files.txt').read_text().splitlines()
        self.originals = {}
        for name in [*self.names, '.gitconfig.local']:
            path = self.target/name
            path.parent.mkdir(parents=True, exist_ok=True)
            content = f'original {name}\n'.encode()
            path.write_bytes(content)
            self.originals[name] = content

    def run_restore(self, *args, target=None):
        return subprocess.run([sys.executable, str(self.repo/'scripts/restore.py'),
                               '--target', str(self.target if target is None else target), *args],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              start_new_session=True, timeout=10)

    def assert_selected(self, selected):
        for name, original in self.originals.items():
            expected = (self.repo/'home'/name).read_bytes() if name in selected else original
            self.assertEqual((self.target/name).read_bytes(), expected, name)

    def assert_refused_without_copy(self, *args, message=None):
        result = self.run_restore(*args, '--apply')
        self.assertNotEqual(result.returncode, 0)
        if message: self.assertIn(message, result.stderr)
        self.assertFalse((self.target/'.dotfiles-backups').exists())
        # A second, valid selection must also remain untouched on preflight failure.
        self.assertEqual((self.target/'.tmux.conf').read_bytes(), self.originals['.tmux.conf'])
        return result

    def test_one_selected_file_preview_apply_backup_and_repeat(self):
        before = {p.relative_to(self.target): p.read_bytes()
                  for p in self.target.rglob('*') if p.is_file()}
        preview = self.run_restore('--file', '.zshrc')
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn('1 files.', preview.stdout)
        self.assertIn('PREVIEW .zshrc', preview.stdout)
        self.assertEqual(before, {p.relative_to(self.target): p.read_bytes()
                                 for p in self.target.rglob('*') if p.is_file()})
        self.assertFalse((self.target/'.dotfiles-backups').exists())
        applied = self.run_restore('--file', '.zshrc', '--apply')
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assert_selected({'.zshrc'})
        backups = list((self.target/'.dotfiles-backups').glob('*/.zshrc'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.originals['.zshrc'])
        repeated = self.run_restore('--file', '.zshrc', '--apply')
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn('UNCHANGED .zshrc', repeated.stdout)
        self.assertEqual(len(list((self.target/'.dotfiles-backups').iterdir())), 1)

    def test_five_selected_files_leave_other_managed_files_untouched(self):
        selected = ['.zshrc', '.zshenv', '.gitconfig', '.tmux.conf', '.config/starship.toml']
        args = [arg for name in selected for arg in ['--file', name]]
        preview = self.run_restore(*args)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn('5 files.', preview.stdout)
        self.assert_selected(set())
        self.assertFalse((self.target/'.dotfiles-backups').exists())
        applied = self.run_restore(*args, '--apply')
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assert_selected(set(selected))
        backups = self.target/'.dotfiles-backups'
        checkpoint = next(backups.iterdir())
        actual = {p.relative_to(checkpoint).as_posix() for p in checkpoint.rglob('*') if p.is_file()}
        self.assertEqual(actual, set(selected))
        for name in selected:
            self.assertEqual((checkpoint/name).read_bytes(), self.originals[name])

    def test_unknown_unmanaged_and_unsafe_values_are_rejected_before_copying(self):
        (self.repo/'home/.private-note').write_text('unmanaged file exists')
        for name in ['.unknown', '.private-note', '.gitconfig.local', 'home/.zshrc',
                     '../home/.zshrc', str(self.repo/'home/.zshrc'), './.zshrc',
                     '.config//starship.toml', '.zshrc/', '']:
            with self.subTest(name=name):
                result = self.assert_refused_without_copy('--file', '.tmux.conf', '--file', name,
                                                          message='Unknown or unmanaged --file')
                self.assertEqual(result.returncode, 2)
                self.assert_selected(set())

    def test_duplicate_selection_restores_once_in_sorted_order(self):
        args = ['--file', '.zshrc', '--file', '.tmux.conf', '--file', '.zshrc']
        result = self.run_restore(*args, '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        copies = [line.split()[1] for line in result.stdout.splitlines() if line.startswith('COPY ')]
        self.assertEqual(copies, ['.tmux.conf', '.zshrc'])
        self.assertIn('2 files.', result.stdout)
        self.assert_selected({'.zshrc', '.tmux.conf'})
        backup = next((self.target/'.dotfiles-backups').iterdir())
        self.assertEqual((backup/'.zshrc').read_bytes(), self.originals['.zshrc'])

    def test_explicit_profiles_remain_compatible(self):
        shell = self.run_restore('--profile', 'shell', '--apply')
        self.assertEqual(shell.returncode, 0, shell.stderr)
        self.assertIn('3 files.', shell.stdout)
        self.assert_selected({'.zshrc', '.zshenv', '.config/starship.toml'})
        all_configs = self.run_restore('--profile', 'all', '--apply')
        self.assertEqual(all_configs.returncode, 0, all_configs.stderr)
        self.assertIn('9 files.', all_configs.stdout)
        self.assert_selected(set(self.names))

    def test_explicit_profile_and_file_are_mutually_exclusive(self):
        for profile in ['all', 'shell']:
            for args in [('--profile', profile, '--file', '.zshrc'),
                         ('--file', '.zshrc', '--profile', profile)]:
                with self.subTest(args=args):
                    result = self.assert_refused_without_copy(*args, message='not allowed with argument')
                    self.assertEqual(result.returncode, 2)
                    self.assert_selected(set())

    def test_selected_files_still_require_valid_managed_manifest(self):
        for content in ['', '.zshrc\n.zshrc\n', '.zshrc\n../escape\n',
                        '.zshrc\n.gitconfig.local\n', '.zshrc\n/absolute\n']:
            with self.subTest(content=content):
                (self.repo/'managed-files.txt').write_text(content)
                self.assert_refused_without_copy('--file', '.zshrc', message='Invalid managed file manifest')
                self.assert_selected(set())

    def test_selected_source_existence_type_and_symlinks_are_checked_before_copying(self):
        source = self.repo/'home/.zshrc'
        source.unlink()
        for mode in ['missing', 'directory', 'symlink']:
            with self.subTest(mode=mode):
                if mode == 'directory': source.mkdir()
                if mode == 'symlink': source.symlink_to(self.repo/'home/.tmux.conf')
                message = 'symlinks' if mode == 'symlink' else 'Missing managed config file'
                self.assert_refused_without_copy('--file', '.tmux.conf', '--file', '.zshrc', message=message)
                if mode == 'directory': source.rmdir()
                if mode == 'symlink': source.unlink()
        config = self.repo/'home/.config'
        config.rename(self.base/'source-config')
        config.symlink_to(self.base/'source-config', target_is_directory=True)
        self.assert_refused_without_copy('--file', '.tmux.conf', '--file', '.config/starship.toml',
                                        message='symlinks')

    def test_selected_destination_conflicts_and_symlinked_parents_fail_before_copying(self):
        outside = self.base/'outside'
        outside.mkdir()
        config = self.target/'.config'
        config.rename(self.base/'original-config')
        for mode in ['parent-link', 'parent-file', 'directory', 'backup-link', 'backup-file']:
            with self.subTest(mode=mode):
                if mode == 'parent-link': config.symlink_to(outside, target_is_directory=True)
                elif mode == 'parent-file': config.write_text('conflict')
                else:
                    config.mkdir()
                    if mode == 'directory': (config/'starship.toml').mkdir()
                    elif mode == 'backup-link': (self.target/'.dotfiles-backups').symlink_to(outside)
                    else: (self.target/'.dotfiles-backups').write_text('conflict')
                result = self.run_restore('--file', '.tmux.conf', '--file', '.config/starship.toml', '--apply')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.target/'.tmux.conf').read_bytes(), self.originals['.tmux.conf'])
                self.assertEqual(list(outside.iterdir()), [])
                if config.is_symlink() or config.is_file(): config.unlink()
                else: shutil.rmtree(config)
                backup = self.target/'.dotfiles-backups'
                if backup.is_symlink() or backup.is_file(): backup.unlink()
                self.assertFalse(backup.exists())

    def test_selected_destination_file_symlink_is_backed_up_without_following_it(self):
        original = self.base/'original'
        original.write_text('keep me')
        link = self.target/'.zshrc'
        link.unlink()
        link.symlink_to(original)
        result = self.run_restore('--file', '.zshrc', '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(original.read_text(), 'keep me')
        backup = next((self.target/'.dotfiles-backups').glob('*/.zshrc'))
        self.assertTrue(backup.is_symlink())
        self.assertEqual(backup.readlink(), original)
        self.assert_selected({'.zshrc'})

    def test_selected_target_and_destination_overlap_are_rejected(self):
        result = self.run_restore('--file', '.zshrc', '--apply', target=self.repo/'home')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must not be inside the repository', result.stderr)
        nested = self.base/'.config/mermaid'
        nested.parent.mkdir()
        self.repo.rename(nested)
        self.repo = nested
        result = self.run_restore('--file', '.config/mermaid/pptr.json', '--apply', target=self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('overlaps the repository', result.stderr)
        self.assertFalse((self.base/'.dotfiles-backups').exists())
        self.assertFalse((self.repo/'pptr.json').exists())


if __name__ == '__main__':
    unittest.main()
