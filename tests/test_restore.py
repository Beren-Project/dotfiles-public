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
            repo = target/'project/dotfiles'
            (repo/'scripts').mkdir(parents=True)
            shutil.copy2(ROOT/'scripts/restore.py', repo/'scripts/restore.py')
            payload = repo/'home'
            (payload/'project/dotfiles').mkdir(parents=True)
            (payload/'.aaa').write_text('must not be copied')
            (payload/'project/dotfiles/new-file').write_text('collision')
            result = subprocess.run([sys.executable, str(repo/'scripts/restore.py'),
                '--target', str(target), '--apply'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((target/'.aaa').exists())
            self.assertFalse((repo/'new-file').exists())

    def test_repository_overlap_rejected(self):
        self.assertNotEqual(self.run_restore(ROOT/'home', True).returncode, 0)

if __name__ == '__main__':
    unittest.main()
