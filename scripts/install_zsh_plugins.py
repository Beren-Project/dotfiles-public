#!/usr/bin/env python3
"""Install pinned standalone plugins. Never invoked by shell startup."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def git(*args):
    return subprocess.run(['git', *map(str, args)], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'}).stdout.strip()


def install(root, plugins):
    for name, spec in plugins.items():
        if not re.fullmatch(r'zsh-[a-z-]+', name) or not re.fullmatch(r'[0-9a-f]{40}', spec['revision']):
            raise ValueError(f'Invalid plugin pin: {name}')
    root = root.expanduser()
    # Refuse symlinks rather than accidentally writing into another installation.
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError(f'Plugin root contains a symlink: {root}')
    root.mkdir(parents=True, exist_ok=True)
    for name, spec in plugins.items():
        dst = root / name
        if dst.exists() or dst.is_symlink():
            if dst.is_symlink() or not (dst / '.git').is_dir():
                raise ValueError(f'Refusing existing non-repository: {dst}')
            if (git('-C', dst, 'remote', 'get-url', 'origin') != spec['url'] or
                    git('-C', dst, 'rev-parse', 'HEAD') != spec['revision'] or
                    git('-C', dst, 'status', '--porcelain', '--untracked-files=all', '--ignored')):
                raise ValueError(f'Refusing modified or mismatched installation: {dst}. Move it aside and rerun.')
            print(f'UNCHANGED {name}')
            continue
        with tempfile.TemporaryDirectory(prefix=f'.{name}-', dir=root) as tmp:
            checkout = Path(tmp) / 'checkout'
            git('init', checkout)
            git('-C', checkout, 'remote', 'add', 'origin', spec['url'])
            git('-C', checkout, 'fetch', '--depth=1', 'origin', spec['revision'])
            git('-C', checkout, 'checkout', '--detach', 'FETCH_HEAD')
            if git('-C', checkout, 'rev-parse', 'HEAD') != spec['revision']:
                raise ValueError(f'Revision verification failed: {name}')
            if not (checkout / f'{name}.zsh').is_file():
                raise ValueError(f'Plugin entrypoint missing: {name}')
            checkout.rename(dst)
        print(f'INSTALLED {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'zsh/plugins',
                        help='Plugin directory (default: XDG data home/zsh/plugins)')
    args = parser.parse_args()
    plugins = json.loads(Path(__file__).with_name('zsh-plugins.json').read_text())
    try:
        install(args.target, plugins)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        parser.exit(1, f'Installation stopped: {detail}\n')


if __name__ == '__main__':
    main()
