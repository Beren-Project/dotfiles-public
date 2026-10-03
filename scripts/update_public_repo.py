#!/usr/bin/env python3
"""Preview a fresh public snapshot; --apply mirrors it into the public Git repo."""
import argparse
import contextlib
import difflib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

# Preview must not leave import caches in either repository.
sys.dont_write_bytecode = True
from export_public import export
from terminal_colors import TerminalColors, color_enabled

ROOT = Path(__file__).resolve().parents[1]


def safe_path(path):
    path = path.expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError(f'Path must not contain symlinks: {path}')
    return path.resolve()


def git(target, *args):
    # Inherited Git overrides must not redirect these checks to another repo.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    result = subprocess.run(
        ['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
         '-C', str(target), *args], env=env, capture_output=True)
    if result.returncode:
        raise ValueError(f'Git check failed: {result.stderr.decode(errors="replace").strip()}')
    return result.stdout


def validate_destination(root, target):
    if root == target or root in target.parents or target in root.parents:
        raise ValueError('Public destination must be separate from the source repository.')
    if not target.is_dir() or not (target/'.git').is_dir():
        raise ValueError('Destination must exist with its own .git directory (no linked worktrees).')
    safe_path(target/'.git')
    top = Path(os.fsdecode(git(target, 'rev-parse', '--show-toplevel')).rstrip('\n'))
    git_dir = Path(os.fsdecode(git(target, 'rev-parse', '--absolute-git-dir')).rstrip('\n'))
    if top != target or git_dir != target/'.git':
        raise ValueError('Destination must be the root of its own non-bare Git repository.')
    entries = git(target, 'ls-files', '--stage', '-v', '-z').split(b'\0')
    for entry in filter(None, entries):
        tag, mode, *_ = entry.split(b' ', 2)
        if tag.islower() or tag == b'S':
            raise ValueError('Refusing assume-unchanged or skip-worktree index entries.')
        if mode == b'160000':
            raise ValueError('Refusing a destination containing Git submodules.')


def inventory(root, preserve_git=False):
    """Read regular files and directories without traversing any symlink."""
    files, directories = {}, set()

    def visit(directory):
        for path in sorted(directory.iterdir()):
            name = path.relative_to(root).as_posix()
            if preserve_git and name == '.git':
                continue
            if path.is_symlink():
                raise ValueError(f'Refusing symlink: {path}')
            if path.name == '.git':
                raise ValueError(f'Refusing nested Git metadata: {path}')
            metadata = path.stat()
            if stat.S_ISDIR(metadata.st_mode):
                directories.add(name)
                visit(path)
            elif stat.S_ISREG(metadata.st_mode):
                if preserve_git and metadata.st_nlink != 1:
                    raise ValueError(f'Refusing multiply linked destination file: {path}')
                files[name] = (path.read_bytes(), stat.S_IMODE(metadata.st_mode))
            else:
                raise ValueError(f'Refusing non-regular file: {path}')

    visit(root)
    return files, directories


def dirty_status(target):
    return git(target, 'status', '--porcelain=v1', '--untracked-files=all', '--ignored=matching')


def show_plan(before, after, old_dirs, new_dirs, show_diff, out, colors=None):
    colors = TerminalColors() if colors is None else colors
    additions = sorted(after.keys() - before.keys())
    changes = sorted(name for name in before.keys() & after.keys() if before[name] != after[name])
    deletions = sorted(before.keys() - after.keys())
    removed_dirs = sorted(old_dirs - new_dirs, key=lambda name: (-len(Path(name).parts), name))
    for label, names in [('ADD', additions), ('CHANGE', changes), ('DELETE', deletions)]:
        for name in names:
            print(f'{colors.status(label)}{" " * (7 - len(label))} {name!r}', file=out)
            old, old_mode = before.get(name, (b'', None))
            new, new_mode = after.get(name, (b'', None))
            if old_mode is not None and new_mode is not None and old_mode != new_mode:
                print(f'  mode {old_mode:04o} -> {new_mode:04o}', file=out)
            if not show_diff or old == new:
                continue
            try:
                if b'\0' in old or b'\0' in new:
                    raise UnicodeError()
                old_lines = old.decode('utf-8').splitlines(keepends=True)
                new_lines = new.decode('utf-8').splitlines(keepends=True)
            except UnicodeError:
                print('  Binary or non-UTF-8 contents differ; diff omitted.', file=out)
                continue
            for index, line in enumerate(difflib.unified_diff(old_lines, new_lines,
                    fromfile=f'public/{name!r}', tofile=f'snapshot/{name!r}')):
                out.write(colors.diff_line(line, index))
                if not line.endswith('\n'):
                    out.write('\n\\ No newline at end of file\n')
    for name in removed_dirs:
        print(f'{colors.status("RMDIR")}   {name!r}', file=out)
    unchanged = len(before.keys() & after.keys()) - len(changes)
    print(f'Summary: add={len(additions)}, change={len(changes)}, delete={len(deletions)}, '
          f'unchanged={unchanged}, remove_dirs={len(removed_dirs)}', file=out)
    return additions, changes, deletions, removed_dirs


def update(root, target, apply=False, show_diff=False, out=None, color='auto'):
    out = sys.stdout if out is None else out
    colors = TerminalColors(color_enabled(color, out))
    root, target = safe_path(root), safe_path(target)
    safe_path(root/'public-files.txt')
    validate_destination(root, target)
    before, old_dirs = inventory(target, preserve_git=True)
    status = dirty_status(target)
    with tempfile.TemporaryDirectory(prefix='dotfiles-public-sync-') as directory:
        snapshot = Path(directory)/'snapshot'
        with contextlib.redirect_stdout(out):
            export(root, snapshot)
        after, new_dirs = inventory(snapshot)
        if not after:
            raise ValueError('Refusing an empty public snapshot.')
        print(f'{"Apply" if apply else "Preview"}: {root} -> {target}', file=out)
        additions, changes, deletions, removed_dirs = show_plan(
            before, after, old_dirs, new_dirs, show_diff, out, colors)
        if status:
            print('Destination has existing changes (including untracked/ignored files):', file=out)
            print(status.decode(errors='replace').rstrip(), file=out)
        if not apply:
            print('Preview only; destination and Git metadata were not modified.', file=out)
            return
        if status:
            raise ValueError('Refusing to apply: public repository is not clean.')
        # Recheck immediately before writes; do not sync while another process edits the repo.
        validate_destination(root, safe_path(target))
        if dirty_status(target) or inventory(target, preserve_git=True) != (before, old_dirs):
            raise ValueError('Destination changed during preflight; rerun preview.')
        for name in deletions:
            safe_path(target/name).unlink()
        for name in removed_dirs:
            safe_path(target/name).rmdir()
        for name in additions + changes:
            destination = safe_path(target/name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Replace each file atomically instead of writing through an existing link.
            with tempfile.NamedTemporaryFile(prefix='.public-sync-', dir=destination.parent,
                                             delete=False) as staging:
                staged_path = Path(staging.name)
            try:
                shutil.copy2(snapshot/name, staged_path)
                os.replace(staged_path, destination)
            finally:
                staged_path.unlink(missing_ok=True)
        if inventory(target, preserve_git=True) != (after, new_dirs):
            raise ValueError('Post-sync verification failed; inspect the public working tree.')
        print('Applied and verified. Changes remain unstaged; no commit or push performed.', file=out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path.home()/'project/dotfiles-public',
                        help='Existing public Git repository (default: ~/project/dotfiles-public)')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--diff', action='store_true', help='Show public-to-snapshot text differences')
    parser.add_argument('--color', choices=['auto', 'always', 'never'], default='auto',
                        help='ANSI colors: auto for terminal output (default), always, or never; '
                             'NO_COLOR disables colors in every mode, even when empty')
    args = parser.parse_args()
    try:
        update(ROOT, args.target, args.apply, args.diff, color=args.color)
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Public sync failed: {exc}\n')


if __name__ == '__main__':
    main()
