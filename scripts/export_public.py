#!/usr/bin/env python3
"""Export the explicit public file list into a new directory, without Git history."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def export(root, destination):
    names = (root/'public-files.txt').read_text().splitlines()
    files = []
    for name in names:
        path = Path(name)
        if (not name or path.is_absolute() or '..' in path.parts or
                any(part in {'.git', 'reference', '.gitconfig.local'} for part in path.parts)):
            raise ValueError(f'Unsafe public manifest entry: {name}')
        source = root/path
        if any(p.is_symlink() for p in [source, *source.parents]):
            raise ValueError(f'Symlink in public source: {name}')
        if not source.is_file():
            raise ValueError(f'Missing public file: {name}')
        files.append((source, path))
    if len(set(names)) != len(names):
        raise ValueError('Duplicate public manifest entries')
    destination = destination.expanduser().absolute()
    if any(p.is_symlink() for p in destination.parents):
        raise ValueError('Destination parent must not be a symlink')
    destination.mkdir(parents=True, exist_ok=False)
    for source, relative in files:
        target = destination/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print(f'Exported {len(files)} reviewed files to {destination}; no Git history copied.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New, nonexistent directory')
    args = parser.parse_args()
    try:
        export(ROOT, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Export failed: {exc}\n')


if __name__ == '__main__':
    main()
