import importlib.util
import io
import os
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    with patch.object(sys, 'path', [str(ROOT/'scripts'), *sys.path]):
        spec.loader.exec_module(result)
    return result


class PublicPreparationTests(unittest.TestCase):
    def test_identity_include_is_optional_and_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); config=home/'.gitconfig'
            config.write_bytes((ROOT/'home/.gitconfig').read_bytes())
            env={**os.environ, 'HOME':tmp, 'XDG_CONFIG_HOME':str(home/'.config'),
                 'GIT_CONFIG_NOSYSTEM':'1', 'GIT_CONFIG_GLOBAL':str(config), 'GIT_CONFIG_COUNT':'0'}
            def get(key):
                return subprocess.run(['git','config','--global','--includes','--get',key],env=env,capture_output=True,text=True)
            self.assertEqual(get('core.pager').stdout.strip(),'delta')
            self.assertEqual(get('user.email').returncode,1)
            (home/'.gitconfig.local').write_text('[user]\nname = Example\nemail = example@example.invalid\n[core]\npager = less\n')
            self.assertEqual(get('user.email').stdout.strip(),'example@example.invalid')
            self.assertEqual(get('core.pager').stdout.strip(),'less')

    def test_profiles_and_personal_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); repo=base/'repo'; target=base/'target'; target.mkdir()
            shutil.copytree(ROOT/'home',repo/'home'); (repo/'scripts').mkdir()
            shutil.copy2(ROOT/'scripts/restore.py',repo/'scripts/restore.py')
            shutil.copy2(ROOT/'managed-files.txt', repo/'managed-files.txt')
            (repo/'home/.gitconfig.local').write_text('personal source')
            (target/'.gitconfig.local').write_text('personal target')
            (target/'.gitconfig').write_text('keep git')
            (target/'.zshrc').write_text('old shell')
            cmd=[sys.executable,str(repo/'scripts/restore.py'),'--target',str(target),'--profile','shell']
            preview=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(preview.returncode,0,preview.stderr)
            self.assertEqual((target/'.zshrc').read_text(),'old shell')
            self.assertFalse((target/'.dotfiles-backups').exists())
            result=subprocess.run(cmd+['--apply'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('3 files.',result.stdout)
            self.assertEqual((target/'.gitconfig').read_text(),'keep git')
            self.assertEqual((target/'.gitconfig.local').read_text(),'personal target')
            self.assertEqual(next((target/'.dotfiles-backups').glob('*/.zshrc')).read_text(),'old shell')
            for name in ['.zshrc','.zshenv','.config/starship.toml']:
                self.assertEqual((target/name).read_bytes(),(repo/'home'/name).read_bytes())
            self.assertFalse((target/'.bashrc').exists())
            result=subprocess.run([sys.executable,str(repo/'scripts/restore.py'),'--target',str(target),'--apply'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((target/'.gitconfig.local').read_text(),'personal target')
            output=io.StringIO()
            self.assertEqual(module('compare_configs').compare(repo/'home',target,out=output),0)
            self.assertNotIn('.gitconfig.local',output.getvalue())
            subprocess.run(['git','init','-q',str(repo)],check=True)
            shutil.copy2(ROOT/'.gitignore',repo/'.gitignore')
            ignored=subprocess.run(['git','-C',str(repo),'check-ignore','--no-index','home/.gitconfig.local'],capture_output=True)
            self.assertEqual(ignored.returncode,0)

    def test_export_manifest_and_existing_destination(self):
        exporter=module('export_public')
        with tempfile.TemporaryDirectory() as tmp:
            destination=Path(tmp)/'public'
            exporter.export(ROOT,destination)
            names=set((ROOT/'public-files.txt').read_text().splitlines())
            actual={str(p.relative_to(destination)) for p in destination.rglob('*') if p.is_file()}
            self.assertEqual(actual,names)
            self.assertIn('scripts/terminal_colors.py', names)
            self.assertFalse((destination/'.git').exists())
            self.assertFalse((destination/'reference').exists())
            self.assertFalse((destination/'home/.gitconfig.local').exists())
            managed=set((destination/'managed-files.txt').read_text().splitlines())
            self.assertEqual({name[5:] for name in names if name.startswith('home/')},managed)
            for document in destination.rglob('*.md'):
                for link in re.findall(r'\]\(([^)]+)\)',document.read_text()):
                    if '://' in link or link.startswith('#'): continue
                    path=link.split('#',1)[0]
                    self.assertTrue((document.parent/path).exists(),f'{document.name}: missing {link}')
                for script in re.findall(r'\bscripts/[A-Za-z0-9_-]+\.py\b', document.read_text()):
                    self.assertTrue((destination/script).is_file(),f'{document.name}: missing {script}')
            evidence=[p for p in actual if p.startswith('docs/benchmarks/')]
            self.assertEqual(evidence,['docs/benchmarks/zsh-2026-09-17/summary.json'])
            summary=json.loads((destination/evidence[0]).read_text())
            self.assertIn('variants',summary)
            for name in actual:
                content=(destination/name).read_text()
                self.assertNotIn(str(Path.home()),content,name)
                self.assertNotRegex(content,r'/home/[a-zA-Z0-9_.-]+/',name)
            for script in ['benchmark_zsh.py','profile_zsh.py','preview_zsh.py',
                           'compare_configs.py','update_public_repo.py']:
                help_result=subprocess.run([sys.executable,str(destination/'scripts'/script),'--help'],
                    capture_output=True,text=True)
                self.assertEqual(help_result.returncode,0,help_result.stderr)
            target = Path(tmp)/'target'
            target.mkdir()
            compared = subprocess.run(
                [sys.executable, '-B', str(destination/'scripts/compare_configs.py'),
                 '--target', str(target), '--diff', '--color=always'],
                env={key: value for key, value in os.environ.items() if key != 'NO_COLOR'},
                capture_output=True, text=True, timeout=10)
            self.assertEqual(compared.returncode, 1, compared.stderr)
            self.assertIn('\x1b[31mMISSING\x1b[0m', compared.stdout)
            with self.assertRaises(FileExistsError): exporter.export(ROOT,destination)


if __name__ == '__main__': unittest.main()
