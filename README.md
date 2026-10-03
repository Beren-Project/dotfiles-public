# Dotfiles

Personal shell, Git, and terminal settings, developed for Ubuntu first.
The initial configuration snapshot was captured on 2026-09-14.
Configs live in `home/`, mirroring paths in the user's home directory.
`managed-files.txt` explicitly lists the nine configs restored and compared;
generated caches and unlisted local files are excluded.

## Operating system target

Ubuntu is the primary development target. Setup instructions, dependency paths,
and shell behavior are developed and validated on Ubuntu first.

| Environment | Project status |
| --- | --- |
| Ubuntu on WSL2, x86_64 | Current development and test environment |
| Native Ubuntu | Intended target; not separately validated yet |
| Other Linux distributions | Compatibility not validated; paths and dependencies may need adjustment |
| Native Windows and macOS | Outside the current target |

The machine inspected on 2026-09-15 reports **Ubuntu 26.04.1 LTS on WSL2**.
This records the tested environment, not a minimum Ubuntu version or a claim
that every Ubuntu release is supported. Windows Terminal is the terminal host;
the shell and restore tools run inside Ubuntu.

See [environment details and checks](docs/SETUP.md#operating-system-and-environment)
before setting up another machine, and [validation evidence](docs/VALIDATION.md)
for the scope of completed checks.

## What's included

| Settings | Files under `home/` |
| --- | --- |
| Zsh and Bash | `.zshrc`, `.zshenv`, `.bashrc`, `.profile` |
| Git and delta | `.gitconfig` |
| tmux and Zellij | `.tmux.conf`, `.config/zellij/config.kdl` |
| Starship prompt | `.config/starship.toml` |
| Mermaid browser launcher used by the shell | `.config/mermaid/pptr.json` |

No custom Vim, Neovim, or Helix configuration was found in the usual home or
`~/.config` locations. Windows Terminal settings are not included; the
setup notes contain the Shift+Enter binding to add on Windows.

The Zsh configuration is framework-free, with native completion, three optional
standalone plugins, and the existing Starship prompt. See [setup and preview](docs/SETUP.md)
for plugin installation and trying the shell before activation.

## Restore on a replacement machine

1. Install Git and Python 3, then clone your published repository.
2. From its directory, check dependencies, then preview the changes:

   ```sh
   python3 scripts/check_dependencies.py
   python3 scripts/restore.py
   ```

3. Create your local Git identity as described in [publication and setup notes](docs/PUBLIC_RELEASE.md), then apply the configuration:

   ```sh
   python3 scripts/restore.py --apply
   ```

4. Install the dependencies listed in [setup notes](docs/SETUP.md), then open
   a new terminal. Restore credentials separately and authenticate GitHub CLI
   if you use its Git credential helper.

Existing changed files move into `~/.dotfiles-backups/<UTC timestamp>/` before
replacement. Identical files are skipped. Destination directory conflicts and
symlinked parent directories are rejected before copying. Existing file
symlinks are backed up as links, without modifying the files they point to.
To undo a replacement, copy its old file from the backup to the original path;
newly created files have no previous version to restore.

To rehearse in a disposable directory:

```sh
python3 scripts/restore.py --target /tmp/dotfiles-demo
python3 scripts/restore.py --target /tmp/dotfiles-demo --apply
```

Use `--profile shell` to restore only `.zshrc`, `.zshenv`, and Starship.
The default `--profile all` restores all shared configs; `.gitconfig.local` is
always excluded.

Select individual managed configs with repeatable `--file` arguments:

```sh
python3 scripts/restore.py --file .zshrc --file .zshenv \
  --file .gitconfig --file .tmux.conf --file .config/starship.toml
```

This previews only those five files; append `--apply` to restore the same
selection with the usual backups and safety checks. Each value must exactly
match `managed-files.txt`. Duplicates restore once, in sorted path order.
`--file` cannot be combined with an explicit `--profile`. Without either
selection option, all managed configs are restored as before.

The script copies files; it does not install applications or change the default
shell. These are Linux configs using the standard `~/.config` location.

## Keep the backup current

Compare the managed configs without modifying either copy:

```sh
python3 scripts/compare_configs.py
python3 scripts/compare_configs.py --diff
python3 scripts/compare_configs.py --diff --color=always | less -R
python3 scripts/compare_configs.py --diff --color=never > config.diff
```

The default reports file status only. `--diff` shows repository-to-target text
changes and can reveal sensitive values in live configs. Differences can reflect
intentional portability edits; neither side is automatically newer or better.
Use `--target /path/to/home` to compare another home directory.

Both review commands support `--color {auto,always,never}` (default: `auto`).
Automatic colors require a terminal; piped or redirected output stays plain.
`always` preserves colors through pipes; `never` disables them. Presence of
`NO_COLOR`, even empty, disables colors in every mode, including `always`.


Edit the version in `home/` and restore it, or copy individual changed settings
from your home directory back into their corresponding paths here. Review
those changes before committing. Do not copy your entire home or `.config`
directory: those contain credentials, caches, and application state.

Git identity belongs in the untracked `~/.gitconfig.local`, included by the
shared `.gitconfig`. Create that local file before restoring Git settings; see
[identity migration and public export](docs/PUBLIC_RELEASE.md). No credentials, shell histories, browser profiles,
private keys, or downloaded plugin trees are included. Secret-pattern checks
are a useful aid, not a guarantee that future edits are safe to publish.

Once reviewed, initialize Git locally if needed, inspect the files you stage,
commit them, and connect your chosen GitHub repository. Git initialization,
staging, commits, and publishing are left to you.

## Update the separate public repository

`dotfiles-private` is the canonical source; `~/project/dotfiles-public` keeps its
own Git history. From the private repository, preview and then apply a fresh
allowlisted snapshot:

```sh
python3 scripts/update_public_repo.py
python3 scripts/update_public_repo.py --apply
```

The command exports current sources into a temporary directory using
`public-files.txt`; existing `public-export/` directories are not used. Preview
leaves the public repository unchanged. Apply requires a clean destination,
adds and replaces exported files, and deletes files outside the current public
allowlist while preserving `.git/`. Changes remain unstaged for your review.
See [recurring synchronization](docs/PUBLIC_RELEASE.md#recurring-synchronization)
for safety checks, diff output, and alternate destinations.

## Validation

```sh
python3 -B -m unittest discover -s tests -v
zsh -n home/.zshrc
zsh -n home/.zshenv
bash -n home/.bashrc
sh -n home/.profile
```

If standalone plugins are installed, include their integration checks:

```sh
DOTFILES_TEST_PLUGINS="${XDG_DATA_HOME:-$HOME/.local/share}/zsh/plugins" \
  python3 -B -m unittest discover -s tests -v
```

Without that variable, the standalone-plugin integration test is skipped.
Starship-specific tests are also skipped when Starship is unavailable.

See [validation notes](docs/VALIDATION.md) for the checks performed on this snapshot.

For a fresh public snapshot and the future bootstrap interface, see
[public release notes](docs/PUBLIC_RELEASE.md). No existing Git history is exported.
