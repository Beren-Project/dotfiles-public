#!/usr/bin/env python3
"""Preview repository Zsh in a child shell, keeping startup caches outside home/."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    with tempfile.TemporaryDirectory(prefix='dotfiles-zsh-preview-') as directory:
        for name in ('.zshenv', '.zshrc'):
            shutil.copy2(ROOT/'home'/name, Path(directory)/name)
        env = {**os.environ, 'ZDOTDIR': directory,
               'STARSHIP_CONFIG': str(ROOT/'home/.config/starship.toml')}
        try:
            return subprocess.call(['zsh', '-i'], env=env)
        except KeyboardInterrupt:
            return 130


if __name__ == '__main__':
    raise SystemExit(main())
