import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/install_zsh_plugins.py'
spec=importlib.util.spec_from_file_location('installer',SCRIPT)
installer=importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def test_install_repeat_conflicts_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); source=base/'source'; source.mkdir()
            installer.git('init',source)
            (source/'zsh-example.zsh').write_text('# fixture\n')
            installer.git('-C',source,'add','zsh-example.zsh')
            installer.git('-C',source,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','fixture')
            revision=installer.git('-C',source,'rev-parse','HEAD')
            pins={'zsh-example':{'url':str(source),'revision':revision}}
            root=base/'plugins'
            installer.install(root,pins); installer.install(root,pins)
            (root/'zsh-example/zsh-example.zsh').write_text('modified')
            with self.assertRaises(ValueError): installer.install(root,pins)
            self.assertEqual((root/'zsh-example/zsh-example.zsh').read_text(),'modified')
            wrong={'zsh-example':{'url':str(source),'revision':'0'*40}}
            with self.assertRaises(ValueError): installer.install(root,wrong)
            failed=base/'failed'
            with self.assertRaises(subprocess.CalledProcessError): installer.install(failed,wrong)
            self.assertEqual(list(failed.iterdir()),[])

if __name__ == '__main__': unittest.main()
