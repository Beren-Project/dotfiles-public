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

if __name__ == '__main__':
    unittest.main()
