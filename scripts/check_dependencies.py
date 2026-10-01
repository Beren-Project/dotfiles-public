#!/usr/bin/env python3
"""Report current-machine dependencies without installing tools or sourcing configs."""
import argparse
import configparser
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def report(root=ROOT, home=None, environ=None, out=sys.stdout):
    home = Path.home() if home is None else Path(home)
    environ = os.environ if environ is None else environ
    def command(name, explanation):
        location = shutil.which(name, path=environ.get('PATH', ''))
        print(f'{"FOUND" if location else "MISSING"}: {name} — {explanation}'
              + (f' ({location})' if location else ''), file=out)
        return location
    def path_check(path, explanation, executable=False, alternative=None):
        path = Path(path)
        present = path.is_file() and os.access(path, os.X_OK if executable else os.R_OK)
        state = 'FOUND' if present else ('PATH MISMATCH' if alternative else 'MISSING')
        print(f'{state}: {path} — {explanation}'
              + (f'; found elsewhere: {alternative}' if not present and alternative else ''), file=out)
    print('Current machine and inherited PATH only; missing tools do not block restoration.', file=out)
    for name, description in {
        'zsh':'interactive shell', 'git':'version control and plugin installer',
        'delta':'required by configured Git pager and interactive diff filter',
        'gh':'configured Git credential helper; authentication is not checked',
        'starship':'optional prompt', 'tmux':'optional terminal multiplexer',
        'zellij':'optional terminal multiplexer', 'cargo':'optional Rust tools',
        'juliaup':'optional Julia manager', 'uv':'optional Python tools',
        'fnm':'optional Node manager', 'direnv':'optional directory environments',
        'zoxide':'optional directory navigation', 'fzf':'optional fuzzy search',
        'broot':'optional Bash launcher', 'mmdc':'optional Mermaid rendering',
    }.items():
        command(name, description)
    config = configparser.RawConfigParser(strict=False)
    with (root/'home/.gitconfig').open() as stream:
        config.read_file(stream)
    for section in config.sections():
        if section.startswith('credential ') and config.has_option(section, 'helper'):
            helper = config.get(section, 'helper').strip()
            parts = shlex.split(helper.lstrip('!'))
            if parts and parts[0].startswith('/'):
                path_check(parts[0], f'{section} helper', executable=True,
                           alternative=shutil.which(Path(parts[0]).name, path=environ.get('PATH','')))
    browser = json.loads((root/'home/.config/mermaid/pptr.json').read_text())['executablePath']
    path_check(browser, 'Mermaid configured browser', executable=True,
               alternative=shutil.which(Path(browser).name, path=environ.get('PATH','')))
    plugins = json.loads((root/'scripts/zsh-plugins.json').read_text())
    data = Path(environ.get('XDG_DATA_HOME') or home/'.local/share')
    for name in plugins:
        path_check(data/'zsh/plugins'/name/f'{name}.zsh', 'optional plugin entrypoint; revision not verified')
    for relative in ['.cargo/env','.local/bin/env','.julia/juliaup/completions/zsh.zsh',
                     '.julia/juliaup/completions/bash.sh','.config/broot/launcher/bash/br']:
        path_check(home/relative, 'optional generated integration file')
    for path in ['/usr/share/doc/fzf/examples/completion.zsh',
                 '/usr/share/doc/fzf/examples/key-bindings.zsh']:
        path_check(path, 'optional Ubuntu fzf integration')
    for path in [home/'.zfunc', home/'.juliaup/bin', Path('/opt/nvim-linux-x86_64/bin')]:
        print(f'{"FOUND" if path.is_dir() else "MISSING"}: {path} — optional completion/tool directory', file=out)
    print('Manual verification: Nerd Font appearance, application compatibility, and authentication.', file=out)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        report()
    except (OSError, ValueError, KeyError, configparser.Error) as exc:
        print(f'Dependency check failed: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
