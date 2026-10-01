"""Read-only reports against controlled fixtures."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result
comparison = module('compare_configs')
dependencies = module('check_dependencies')

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
