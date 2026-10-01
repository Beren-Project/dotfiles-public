#!/usr/bin/env python3
"""Profile trusted live Zsh configs in temporary directories, without activation.

Requires hyperfine and Zsh. Keeps the real HOME and installed integrations, but
redirects completion dumps and fnm runtime files. Results are written only to
the requested new output directory. No browser helper is invoked.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MARKERS = {
    '# Environment:': 'path', '# History shared': 'history',
    '# Completion:': 'completion', '# Optional developer': 'integrations',
    '# Prompt:': 'prompt_init', '# Standalone plugins.': 'plugins',
    '# Both common': 'bindings', '# Syntax highlighting must': 'highlighting',
}


def instrument(rc):
    lines = ['typeset -F _profile_start=$EPOCHREALTIME']
    previous = 'rc_preamble'
    found = set()
    for line in rc.splitlines():
        for prefix, label in MARKERS.items():
            if line.startswith(prefix):
                found.add(prefix)
                lines += [f'print -u2 -- "PROFILE {previous} $((1000*(EPOCHREALTIME-_profile_start)))"',
                          '_profile_start=$EPOCHREALTIME']
                previous = label
        lines.append(line)
    if found != set(MARKERS):
        raise ValueError('Config section markers changed; update the profiler before running.')
    lines.append(f'print -u2 -- "PROFILE {previous} $((1000*(EPOCHREALTIME-_profile_start)))"')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path.home())
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--warmup', type=int, default=5)
    args = parser.parse_args()
    if args.runs < 2 or args.warmup < 0:
        parser.error('Require --runs >= 2 and --warmup >= 0')
    zsh = shutil.which('zsh'); hyperfine = shutil.which('hyperfine')
    if not zsh or not hyperfine:
        parser.error('Install zsh and hyperfine first')
    configs = {name: (args.source/name).read_text() for name in ('.zshenv', '.zshrc')}
    instrument(configs['.zshrc'])  # Validate before starting any measurements.
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()
    path_entries = os.environ['PATH'].split(':')
    linux_path = ':'.join(p for p in path_entries if not p.startswith('/mnt/'))
    metadata = {
        'source': str(args.source.resolve()),
        'config_sha256': {n: hashlib.sha256(v.encode()).hexdigest() for n, v in configs.items()},
        'os_release': platform.freedesktop_os_release(),
        'kernel': platform.release(), 'architecture': platform.machine(),
        'zsh': subprocess.check_output([zsh, '--version'], text=True).strip(),
        'hyperfine': subprocess.check_output([hyperfine, '--version'], text=True).strip(),
        'path_entries': len(path_entries),
        'removed_for_linux_only': sum(p.startswith('/mnt/') for p in path_entries),
        'runs': args.runs, 'warmup': args.warmup,
        'method': 'Temporary ZDOTDIR and XDG_RUNTIME_DIR; real HOME; non-TTY; sequential variants',
    }
    (output/'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    with tempfile.TemporaryDirectory(prefix='dotfiles-zsh-profile-') as td:
        base = Path(td)
        runtime = base/'runtime'; runtime.mkdir(mode=0o700)
        cases = [
            ('current', [], os.environ['PATH']),
            ('no_global_rcs', ['-o', 'no_global_rcs'], os.environ['PATH']),
            ('bare', ['-f'], os.environ['PATH']),
            ('linux_path_diagnostic', [], linux_path),
        ]
        for label, flags, path_value in cases:
            zdot = base/label; zdot.mkdir()
            for name, content in configs.items():
                (zdot/name).write_text(content)
            env = {**os.environ, 'ZDOTDIR': str(zdot), 'XDG_RUNTIME_DIR': str(runtime),
                   'PATH': path_value}
            command = shlex.join([zsh, *flags, '-i', '-c', 'exit'])
            # Catch startup warnings instead of silently benchmarking a failed integration.
            check = subprocess.run([zsh, *flags, '-i', '-c', 'exit'], env=env,
                                   cwd=ROOT, capture_output=True, text=True, timeout=30)
            if check.returncode or check.stderr:
                (output/f'{label}-error.txt').write_text(check.stderr)
                raise RuntimeError(f'{label}: startup failed or emitted stderr; see output directory')
            result = subprocess.run([hyperfine, '--warmup', str(args.warmup),
                                     '--runs', str(args.runs), '--export-json',
                                     str(output/f'{label}.json'), command],
                                    env=env, cwd=ROOT, capture_output=True, text=True, timeout=300)
            (output/f'{label}-hyperfine.txt').write_text(result.stdout + result.stderr)
            result.check_returncode()
            print(label, result.stdout, flush=True)
            if label == 'bare':
                continue
            (zdot/'.zshenv').write_text('zmodload zsh/zprof\nzmodload zsh/datetime\n' + configs['.zshenv'])
            (zdot/'.zshrc').write_text(instrument(configs['.zshrc']))
            for sample in range(1, 4):
                profile = subprocess.run([zsh, *flags, '-i', '-c', 'zprof'], env=env,
                                         cwd=ROOT, capture_output=True, text=True, timeout=30)
                profile.check_returncode()
                (output/f'{label}-zprof-{sample}.txt').write_text(profile.stdout)
                (output/f'{label}-sections-{sample}.txt').write_text(profile.stderr)
            # Fresh-shell command-table probe: compaudit accesses commands[getent].
            probe = ('zmodload zsh/datetime; typeset -F t=$EPOCHREALTIME; '
                     '(( $+commands[getent] )); '
                     'print -- $((1000*(EPOCHREALTIME-t)))')
            values = [float(subprocess.check_output([zsh, '-f', '-c', probe],
                            env=env, cwd=ROOT, text=True)) for _ in range(3)]
            (output/f'{label}-command-table-ms.json').write_text(json.dumps(values) + '\n')


if __name__ == '__main__':
    main()
