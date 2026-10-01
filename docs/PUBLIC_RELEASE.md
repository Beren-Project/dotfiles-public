# Public snapshot and future bootstrap

`dotfiles-private` remains the canonical source of configuration and tooling.
The separate `dotfiles-public` repository has independent Git history. A first
public snapshot uses fresh Git history; changing visibility on the private
repository would expose historical config contents and commit identity metadata.

## Personal Git identity

The shared Git config includes `~/.gitconfig.local` last. A missing local file is
allowed, but you must supply an identity before making commits. Create it before
restoring the shared `.gitconfig`:

```sh
git config --file "$HOME/.gitconfig.local" user.name "Your chosen name"
git config --file "$HOME/.gitconfig.local" user.email "YOUR_GITHUB_NOREPLY_ADDRESS"
```

Replace the placeholders with your choices. Get your exact GitHub-provided
noreply address from your account email settings; do not guess it. The example
in `examples/gitconfig.local.example` is informational and is not restored.
You can use a personal email locally instead if desired. This file is personal
configuration, not storage for passwords or access tokens.

The local file is Git-ignored and excluded from restoration and comparison even
if accidentally copied under `home/`. After this migration, do not copy a live
`.gitconfig` containing embedded identity back into the shared file.

## Export for review

`public-files.txt` explicitly lists every file in the public snapshot. Review
changes to those files and to the list before every export. The list is a scope
control, not an automatic guarantee against secrets in future edits.

The export includes the profiling report, both benchmark tools, and a reviewed
summary containing numeric samples and version information. Raw profiler output
and machine-specific paths remain in the private archive. The exporter copies
listed files unchanged; sanitization is performed before inclusion in the
manifest, not by automatic redaction during export. Newly generated profiler
output must be reviewed separately before adding it to the public list.

Export regression checks verify local documentation links, referenced Python
tools, the managed config manifest, and exclusion of raw profiling artifacts.

```sh
python3 scripts/export_public.py --output ./public-export
```

The output directory must not exist. The exporter copies only the listed files,
refuses source symlinks, and never copies `.git`, `reference/`, or personal local
Git config. Arbitrary untracked files and caches are not included. Newly added
files are included only after explicitly adding them to the reviewed list.
If copying fails partway, inspect the partial directory and choose a new output
directory for a retry; the exporter does not overwrite existing output.

The historical shell reference remains in the private archive, not the export.
No publication is performed by the exporter. For initial publication into a new
repository, review the snapshot before these user-run steps in its directory:

```sh
git init -b main
git config --local user.name "Your public author name"
git config --local user.email "YOUR_GITHUB_NOREPLY_ADDRESS"
git config --local --get user.name
git config --local --get user.email
git add .
git diff --cached --stat
git commit -m "Add portable dotfiles"
```

Only then connect a new public repository and push it. Keep the original private
remote unchanged. No history rewriting or force-push is needed. The new public
repository URL is chosen at publication time.

## Recurring synchronization

Run from the canonical private repository after reviewing its public files and
running the tests:

```sh
python3 scripts/update_public_repo.py
python3 scripts/update_public_repo.py --diff
python3 scripts/update_public_repo.py --apply
```

The default destination is `~/project/dotfiles-public`. Use `--target PATH` for
another existing public Git repository. The source is always the repository
containing the script; run the maintained command from `dotfiles-private`.
Every invocation calls the existing exporter to build a new temporary snapshot
from `public-files.txt`. It never reads the stale `public-export/` directory.
Content is copied unchanged, so review and sanitization still precede export.

Preview performs only reads in the destination and prints additions, changes,
deletions, obsolete directories, and a summary. `--diff` additionally shows text
changes from `public/...` to `snapshot/...`; binary/non-UTF-8 contents are not
dumped. Exit 0 means preview/apply succeeded, even if preview reports differences;
exit 2 means a safety check or operation failed.

Apply mirrors file contents and permissions, including hidden files. All files
outside the current snapshot and obsolete directories are removed, except the
root `.git/` directory, which is never copied, changed, or traversed by the sync.
The destination must be a separate, ordinary Git repository root with its own
`.git/` directory. Bare repositories and linked worktrees are unsupported.
Overlapping source/destination trees, symlinked paths, nested repositories,
submodules, special files, multiply linked destination files, and an empty
snapshot are refused. Git index flags that can hide edits (`assume-unchanged`
and `skip-worktree`) are also refused.

Apply requires no staged or unstaged changes and no untracked or ignored files.
Ignored files are included in this check to prevent deleting local data silently.
Dirty destinations can still be previewed if their paths pass safety checks.
The destination is checked again immediately before writing, and the result
is verified against the snapshot. Do not edit the destination concurrently.
File replacements are individually atomic; the complete sync is not a transaction.
If an I/O failure interrupts apply, inspect the reported partial working-tree
changes before retrying; dirty-state protection will refuse a blind rerun.

Changes remain unstaged. Review them in the public repository, then stage,
commit, and push yourself. The command never stages, commits, pushes, resets,
or cleans Git, and never transfers private history. After a successful apply,
another preview reports no changes. Another apply requires you to first resolve
the previous unstaged changes; once committed, an unchanged apply is a no-op.

For validation from the public repository, suppress bytecode generation:

```sh
cd ~/project/dotfiles-public
python3 -B -m unittest discover -s tests -v
```

`-B` prevents new `__pycache__` bytecode caches, which are ignored files and
would block a later sync. It does not remove existing caches; the same
dirty/ignored-file safety checks still apply.

## Bootstrap contract

Ubuntu is the first target for future bootstrap development, consistent with the
[project OS policy](../README.md#operating-system-target). Current validation is
on Ubuntu/WSL2; exporting a snapshot does not establish cross-platform support.

The future bootstrap takes a public repository URL and a reviewed full commit
ID, fetches that exact commit into a dedicated checkout, and verifies the checkout
HEAD matches. It must not substitute a moving branch for the pinned revision.
Downloaded configs have one maintained source here, rather than duplicated
editable copies in bootstrap.

After bootstrap installs Python 3, Git, Zsh, Starship, and other desired tools,
run from the pinned checkout:

```sh
python3 scripts/check_dependencies.py
python3 scripts/install_zsh_plugins.py
python3 scripts/restore.py --profile shell
python3 scripts/restore.py --profile shell --apply
```

The shell profile includes exactly `.zshrc`, `.zshenv`, and
`.config/starship.toml`. The default `--profile all` restores all shared managed
configs. Both retain preview, backups, and conflict protections. `--target PATH`
selects a different destination home; it does not change the Git include's home
resolution when Git later reads the config.

The plugin installer installs the revisions in this checkout's plugin manifest.
It does not install the applications themselves. Bootstrap remains responsible
for application installation and personal Git identity setup. Building bootstrap
and publishing the public repository are separate tasks.
