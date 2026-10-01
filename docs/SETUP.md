# Replacement-machine setup

## Install and preview Zsh

Install Zsh, Python 3, Git, Starship, and a Nerd Font for the terminal. This
configuration targets Linux; it was checked with Zsh 5.9 and Starship 1.25.1.
Oh My Zsh and a plugin manager are not required.

Install the three standalone plugins explicitly:

```sh
python3 scripts/install_zsh_plugins.py
```

This installs autosuggestions, history substring search, and syntax highlighting
under `${XDG_DATA_HOME:-~/.local/share}/zsh/plugins`. Upstream URLs and exact
revisions are recorded in `scripts/zsh-plugins.json`. A rerun skips matching
clean installations. Modified, untracked, ignored, or mismatched contents cause
that installation to be refused; previous successful installations remain.
Downloads are staged and verified before each plugin is put into place.
Shell startup never downloads or updates anything.

To update a plugin, review and change its recorded revision, move the existing
plugin directory aside, and rerun the installer. Retain the old directory until
you have tested the replacement. Downloaded plugins are not part of this backup.

Preview the project configuration in a child shell without replacing live files:

```sh
ZDOTDIR="$PWD/home" STARSHIP_CONFIG="$PWD/home/.config/starship.toml" zsh
```

This preview uses your real HOME, installed tools, and shared history. `exit`
returns to your original shell. For an isolated test, restore into a temporary
home and set HOME, ZDOTDIR, XDG_CONFIG_HOME, and XDG_DATA_HOME to paths there,
as the test suite does.

Before activation, run the separate read-only dependency report:

```sh
python3 scripts/check_dependencies.py
```

It uses the current machine's inherited PATH and checks configured file paths.
It does not source configs, install tools, contact services, or check login
credentials. `FOUND` means the executable/file is available, not that a complete
application setup has been tested. `MISSING` reports unavailable dependencies;
`PATH MISMATCH` identifies a configured executable missing at its expected path
when an executable of the same name is on PATH. Missing optional features do not
block restoration. Plugin entrypoints are checked without verifying revisions.
The report exits 0 when complete and 2 for an operational error.

Before restoring all configs, create `~/.gitconfig.local` using the
[identity migration instructions](PUBLIC_RELEASE.md). Then activate:

```sh
python3 scripts/restore.py
python3 scripts/restore.py --apply
```

The restore command applies all managed configs, preserving changed originals
in `~/.dotfiles-backups/<timestamp>/`. Open a new terminal to load the result.
To roll back Zsh, copy `.zshrc` and `.zshenv` from that backup into your home.
Keep an existing terminal open while testing. The earlier project `.zshrc` is
also preserved in the private archive under `reference/`; it is not part of the
public export.

## Everyday behavior

- Shared history: commands from other terminals become available at the next
  prompt. History keeps 10,000 entries; leading-space commands are excluded.
- Emacs editing: Ctrl+A / Ctrl+E move to the start/end of the line.
- Tab completion has a selection menu and case-insensitive matching. Insecure
  completion directories are ignored by `compinit -i`, never blindly trusted.
- Up/Down searches history by substring when the plugin is installed, otherwise
  it navigates ordinary history. Right arrow at the end accepts autosuggestions.
- Shift+Enter inserts a newline if the terminal sends `ESC [ 13 ; 2 u`.
- Starship keeps the existing colorful two-line prompt. On finishing input,
  the old prompt becomes an arrow; the next prompt retains full context.
  Full and collapsed arrows stay bold green, regardless of command exit status.
  They mark input, not results; Zsh's `$?` still reports the actual exit status.
- Missing plugins or Starship leave a usable basic shell. No Git aliases or
  double-Escape sudo shortcut are installed.

For Windows Terminal, add this action to its settings (not included in this repo):

```json
{"command":{"action":"sendInput","input":"\u001b[13;2u"},"keys":"shift+enter"}
```

## Optional developer tools

Cargo loads quietly from `.zshenv` when installed. Juliaup, uv, fnm, direnv,
zoxide, and Ubuntu's fzf integration load only when their dependencies exist.
Tool-generated environment files and `.zfunc` completions are not backed up;
recreate them using their installers. Bash's existing optional broot integration
is unchanged. Zsh includes `/opt/nvim-linux-x86_64/bin` only if it exists.

Install Git, delta, GitHub CLI, tmux, and Zellij for their captured settings.
The Git credential helper uses `/usr/bin/gh`; adjust it for other installation
paths and authenticate separately. Git identity is supplied through the untracked `~/.gitconfig.local` include.

The Mermaid integration requires Mermaid CLI and a browser. Its config points
to `/usr/bin/google-chrome` with the original sandbox-disabling arguments;
review those settings before rendering untrusted content. Pandoc integrations
require their tools separately.

Custom editor settings were not found. This backup does not install software,
change your default shell, or restore projects, OS settings, or credentials.

## Compare before updating the backup

Run `python3 scripts/compare_configs.py` for a sorted summary of managed files.
Use `--target PATH` to select another home (the default is your current home).
Unrelated files are not scanned. Content comparisons are byte-for-byte; file
permissions and ownership are not compared.

Statuses are IDENTICAL, DIFFERENT, MISSING, SYMLINK, TYPE CONFLICT, and UNREADABLE.
Symlinked files and parent directories are reported without following them.
Exit codes: 0 means all files match, 1 means differences or structural conflicts,
and 2 means an operational/read error.

Add `--diff` for unified UTF-8 text differences labeled `repository/...` and
`target/...`; missing target files appear as absent. Binary/non-UTF-8 contents
are not dumped. Diffs may expose private live-config values, so review before
sharing. The direction is descriptive, not an instruction to overwrite files.
Neither tool copies configs or changes Git state.
