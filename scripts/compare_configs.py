#!/usr/bin/env python3
"""Compare managed config contents without copying files or following target symlinks."""
import argparse
from collections import Counter
import difflib
from pathlib import Path
import sys

# Read-only comparison must not leave a cache when importing its renderer.
sys.dont_write_bytecode = True
from terminal_colors import TerminalColors, color_enabled


def compare(source, target, show_diff=False, out=None, names=None, color='auto'):
    out = sys.stdout if out is None else out
    colors = TerminalColors(color_enabled(color, out))
    counts = Counter()
    error = False
    entries = source.rglob('*') if names is None else (source / name for name in names)
    for src in sorted(entries):
        if '.gitconfig.local' in src.relative_to(source).parts:
            continue
        if any(p.is_symlink() for p in (src, *src.parents)):
            raise ValueError(f'Unexpected source symlink: {src}')
        if src.is_dir():
            if names is not None:
                raise ValueError(f'Managed source is a directory: {src}')
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
        print(f'{colors.status(status)}{" " * (13 - len(status))} {relative}', file=out)
        if show_diff and status in ('DIFFERENT', 'MISSING'):
            try:
                if b'\0' in original or b'\0' in (live or b''):
                    raise UnicodeError()
                before = original.decode('utf-8').splitlines(keepends=True)
                after = (live or b'').decode('utf-8').splitlines(keepends=True)
            except UnicodeError:
                print('  Binary or non-UTF-8 contents differ; diff omitted.', file=out)
                continue
            for index, line in enumerate(difflib.unified_diff(before, after,
                    fromfile=f'repository/{relative}', tofile=f'target/{relative}')):
                out.write(colors.diff_line(line, index))
                if not line.endswith('\n'):
                    out.write('\n\\ No newline at end of file\n')
    print('Summary: ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())), file=out)
    return 2 if error else int(any(k != 'IDENTICAL' for k in counts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path.home())
    parser.add_argument('--diff', action='store_true', help='Show contents; may reveal sensitive live values')
    parser.add_argument('--color', choices=['auto', 'always', 'never'], default='auto',
                        help='ANSI colors: auto for terminal output (default), always, or never; '
                             'NO_COLOR disables colors in every mode, even when empty')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / 'home'
    try:
        if not source.is_dir():
            raise ValueError(f'Missing managed config directory: {source}')
        # absolute() preserves symlinks so comparison can report them.
        names = (source.parent/'managed-files.txt').read_text().splitlines()
        if not names or len(set(names)) != len(names) or any(
                not name or Path(name).is_absolute() or '..' in Path(name).parts or
                '.gitconfig.local' in Path(name).parts for name in names):
            raise ValueError('Invalid managed file manifest')
        return compare(source, args.target.expanduser().absolute(), args.diff,
                       names=names, color=args.color)
    except (OSError, ValueError) as exc:
        print(f'Comparison failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
