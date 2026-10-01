#!/usr/bin/env python3
"""Compare managed config contents without copying files or following target symlinks."""
import argparse
from collections import Counter
import difflib
from pathlib import Path
import sys


def compare(source, target, show_diff=False, out=sys.stdout):
    counts = Counter()
    error = False
    for src in sorted(source.rglob('*')):
        if '.gitconfig.local' in src.relative_to(source).parts:
            continue
        if src.is_symlink():
            raise ValueError(f'Unexpected source symlink: {src}')
        if src.is_dir():
            continue
        if not src.is_file():
            raise ValueError(f'Unexpected source file type: {src}')
        relative = src.relative_to(source)
        dst = target / relative
        original = live = None
        try:
            original = src.read_bytes()
            chain = [*reversed(dst.parents), dst]
            if any(p.is_symlink() for p in chain):
                status = 'SYMLINK'
            elif any(p.exists() and not p.is_dir() for p in dst.parents):
                status = 'TYPE CONFLICT'
            elif not dst.exists():
                status = 'MISSING'
            elif not dst.is_file():
                status = 'TYPE CONFLICT'
            else:
                live = dst.read_bytes()
                status = 'IDENTICAL' if original == live else 'DIFFERENT'
        except OSError as exc:
            status = 'UNREADABLE'
            error = True
            print(f'Cannot read {relative}: {exc}', file=out)
        counts[status] += 1
        print(f'{status:13} {relative}', file=out)
        if show_diff and status in ('DIFFERENT', 'MISSING'):
            try:
                if b'\0' in original or b'\0' in (live or b''):
                    raise UnicodeError()
                before = original.decode('utf-8').splitlines(keepends=True)
                after = (live or b'').decode('utf-8').splitlines(keepends=True)
            except UnicodeError:
                print('  Binary or non-UTF-8 contents differ; diff omitted.', file=out)
                continue
            for line in difflib.unified_diff(before, after,
                    fromfile=f'repository/{relative}', tofile=f'target/{relative}'):
                out.write(line)
                if not line.endswith('\n'):
                    out.write('\n\\ No newline at end of file\n')
    print('Summary: ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())), file=out)
    return 2 if error else int(any(k != 'IDENTICAL' for k in counts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path.home())
    parser.add_argument('--diff', action='store_true', help='Show contents; may reveal sensitive live values')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / 'home'
    try:
        if not source.is_dir():
            raise ValueError(f'Missing managed config directory: {source}')
        # absolute() preserves symlinks so comparison can report them.
        return compare(source, args.target.expanduser().absolute(), args.diff)
    except (OSError, ValueError) as exc:
        print(f'Comparison failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
