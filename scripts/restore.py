#!/usr/bin/env python3
"""Preview restoration; pass --apply to copy configs and back up existing files."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply', action='store_true')
parser.add_argument('--target', type=Path, default=Path.home())
selection = parser.add_mutually_exclusive_group()
selection.add_argument('--profile', choices=['all', 'shell'],
                       help='all shared configs (default), or Zsh and Starship only')
selection.add_argument('--file', dest='files', action='append',
                       help='Exact managed-files.txt entry to restore; repeat to select several')
args = parser.parse_args()
repository = Path(__file__).resolve().parents[1]
source = repository / 'home'
target = args.target.expanduser().resolve()
if target == repository or repository in target.parents:
    raise SystemExit('Restore target must not be inside the repository.')
backup = target / '.dotfiles-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
if backup.parent.is_symlink():
    raise SystemExit('Backup directory must not be a symlink.')
if backup.parent.exists() and not backup.parent.is_dir():
    raise SystemExit('Backup path must be a directory.')
if target.exists() and not target.is_dir():
    raise SystemExit('Target must be a directory.')
names = (repository / 'managed-files.txt').read_text().splitlines()
if not names or len(set(names)) != len(names) or any(
        not name or Path(name).is_absolute() or '..' in Path(name).parts or
        '.gitconfig.local' in Path(name).parts for name in names):
    raise SystemExit('Invalid managed file manifest.')
if args.files:
    unknown = list(dict.fromkeys(name for name in args.files if name not in names))
    if unknown:
        parser.error('Unknown or unmanaged --file value(s): ' + ', '.join(repr(name) for name in unknown))
    names = list(dict.fromkeys(args.files))
elif args.profile == 'shell':
    shell_names = ['.zshrc', '.zshenv', '.config/starship.toml']
    if not set(shell_names).issubset(names):
        raise SystemExit('Managed manifest is missing a shell config.')
    names = shell_names
files = sorted(source / name for name in names)
for src in files:
    if any(p.is_symlink() for p in (src, *src.parents)):
        raise SystemExit(f'Source config path must not contain symlinks: {src}')
    if not src.is_file():
        raise SystemExit(f'Missing managed config file: {src}')
for src in files:
    relative = src.relative_to(source)
    dst = target / relative
    # A repository below HOME is normal; only actual destination collisions
    # must be rejected, before any files are moved or copied.
    if dst == repository or repository in dst.parents or dst in repository.parents:
        raise SystemExit(f'Restore destination overlaps the repository: {dst}')
    if src.is_symlink():
        raise SystemExit(f'Refusing source symlink: {src}')
    if any(p.is_symlink() for p in dst.parents if p != target and target in p.parents):
        raise SystemExit(f'Refusing destination under symlink: {dst}')
    if dst.is_dir():
        raise SystemExit(f'Destination is a directory: {dst}')
    if any(p.exists() and not p.is_dir() for p in dst.parents):
        raise SystemExit(f'Destination parent is not a directory: {dst}')
for src in files:
    relative = src.relative_to(source)
    dst = target / relative
    if dst.is_file() and not dst.is_symlink() and dst.read_bytes() == src.read_bytes():
        print(f'UNCHANGED {relative}')
        continue
    print(f'{"COPY" if args.apply else "PREVIEW"} {relative} -> {dst}')
    if not args.apply:
        continue
    if dst.exists() or dst.is_symlink():
        saved = backup / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(saved))
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
print(f'{len(files)} files. Existing files are backed up under {backup} when replaced.')
