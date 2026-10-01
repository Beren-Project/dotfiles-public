# Public snapshot and future bootstrap

The existing repository stays private as an archive. A public snapshot uses
fresh Git history; changing visibility on the old repository would expose its
historical config contents and commit identity metadata.

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
No publication is performed by the exporter. Review the snapshot before these
user-run steps in its directory:

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

## Bootstrap contract

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
