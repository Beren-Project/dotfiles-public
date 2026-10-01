#!/usr/bin/env python3
"""Compare repository Zsh startup with a Git revision in disposable ZDOTDIRs.

Uses the caller's HOME, PATH, installed tools and plugins. Only run with trusted
configs: startup code is executed. Cache and fnm runtime writes are redirected
to temporary directories; the live shell configuration is never replaced.
"""
import argparse
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def measure(configs, runs):
    with tempfile.TemporaryDirectory(prefix='dotfiles-zsh-benchmark-') as directory:
        root = Path(directory)
        runtime = root/'runtime'
        runtime.mkdir(mode=0o700)
        for name, content in configs.items():
            (root/name).write_text(content)
        env = {**os.environ, 'ZDOTDIR': str(root), 'XDG_RUNTIME_DIR': str(runtime)}

        def run(code):
            start = time.perf_counter()
            result = subprocess.run(['zsh', '-i', '-c', code], env=env,
                                    cwd=ROOT, capture_output=True, text=True,
                                    timeout=30)
            elapsed = round(1000 * (time.perf_counter() - start), 2)
            if result.returncode or result.stderr:
                raise RuntimeError(f'Zsh startup failed: {result.stderr}')
            return elapsed, result.stdout

        cold_ms, _ = run('exit')
        warm_ms = [run('exit')[0] for _ in range(runs)]
        # Start profiling before the global zshrc, outside the timed samples.
        (root/'.zshenv').write_text('zmodload zsh/zprof\n' + configs['.zshenv'])
        _, profile = run('zprof')
        table = profile.split('-----------------------------------------------------------------------------------')[1]
        counts = {name: int(calls) for calls, name in re.findall(
            r'^\s*\d+\)\s+(\d+)\s+.*?\s+(\w+)\s*$', table, re.MULTILINE)}
        return {'cold_ms': cold_ms, 'warm_ms': warm_ms,
                'warm_median_ms': statistics.median(warm_ms),
                'warm_profile_calls': {name: counts.get(name, 0)
                                       for name in ('compinit', 'compaudit', 'compdump')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default='HEAD')
    parser.add_argument('--runs', type=int, default=5)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('--runs must be positive')
    revision = subprocess.check_output(
        ['git', 'rev-parse', '--verify', '--end-of-options', args.baseline_ref + '^{commit}'],
        cwd=ROOT, text=True).strip()
    names = ('.zshenv', '.zshrc')
    baseline = {name: subprocess.check_output(
        ['git', 'show', f'{revision}:home/{name}'], cwd=ROOT, text=True) for name in names}
    current = {name: (ROOT/'home'/name).read_text() for name in names}
    print(json.dumps({'baseline_revision': revision,
                      'zsh_version': subprocess.check_output(['zsh', '--version'], text=True).strip(),
                      'windows_path_preserved': True,
                      'baseline': measure(baseline, args.runs),
                      'working_tree': measure(current, args.runs)}, indent=2))


if __name__ == '__main__':
    main()
