# Replacement-machine setup

## Operating system and environment

This project is developed for **Ubuntu first**, with Ubuntu on WSL2 as the
current test environment. Native Ubuntu is also an intended target, but has not
been separately validated. Other Linux distributions may need adapted package
names and paths. Native Windows and macOS are outside the current target.

Environment inspected on 2026-09-15:

| Component | Observed value |
| --- | --- |
| Distribution | Ubuntu 26.04.1 LTS (`VERSION_ID=26.04`, `resolute`) |
| Architecture | x86_64 |
| Runtime | WSL2 |
| Kernel | `6.18.33.2-microsoft-standard-WSL2` |
| Zsh | 5.9 |
| Python | 3.14.4 |

These are observed versions, not minimum requirements. No Ubuntu release range
has been validated. Check a replacement machine before following the setup:

```sh
cat /etc/os-release
uname -srm
zsh --version
python3 --version
```

Run the repository tools inside Ubuntu, including when using Windows Terminal.
The supplied Windows Terminal key binding is a host-terminal setting; it does
not make the dotfiles a native Windows configuration.

Platform assumptions to review when moving machines:

- Ubuntu's global Zsh completion initialization is disabled by `.zshenv`, so
  `.zshrc` can initialize once after adding custom completion directories.
- Optional fzf integration uses Ubuntu package paths under
  `/usr/share/doc/fzf/examples/`. The optional Neovim PATH entry assumes an
  x86_64 installation at `/opt/nvim-linux-x86_64/bin`.
- WSL's inherited Windows PATH entries are preserved. Startup timings can
  therefore differ from native Ubuntu; see the recorded performance checks.

The dependency report below checks executables and paths. It does not certify
OS compatibility or install missing dependencies.

## Install and preview Zsh

Install Zsh, Python 3, Git, Starship, and a Nerd Font for the terminal. The shell
configuration was checked with Zsh 5.9 and Starship 1.25.1 on Ubuntu/WSL2.
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
python3 scripts/preview_zsh.py
```

This preview copies `.zshenv` and `.zshrc` into a temporary ZDOTDIR, so generated
completion caches stay outside `home/`. It uses the repository Starship config
and your real HOME, installed tools, and shared history. `exit` returns to your
original shell and removes the temporary directory. For an isolated test, restore into a temporary
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

The restore command applies only configs listed in `managed-files.txt`, preserving changed originals
in `~/.dotfiles-backups/<timestamp>/`. Open a new terminal to load the result.
To roll back Zsh, copy `.zshrc` and `.zshenv` from that backup into your home.
Keep an existing terminal open while testing. The earlier project `.zshrc` is
also preserved in the private archive under `reference/`; it is not part of the
public export.

To preview just the two Zsh startup files:

```sh
python3 scripts/restore.py --file .zshrc --file .zshenv
```

Append `--apply` for the same selection and normal backups. Repeat `--file`
with exact `managed-files.txt` entries; duplicates restore once in sorted order.
Use either individual files or an explicit `--profile`, never both. Omitting
both keeps the default of restoring all managed configs.

## Everyday behavior

- Shared history: commands from other terminals become available at the next
  prompt. History keeps 10,000 entries; leading-space commands are excluded.
- Emacs editing: Ctrl+A / Ctrl+E move to the start/end of the line.
- Interactive comments are enabled, so pasted command blocks can include `#`
  comment lines. Quote literal arguments containing `#` when necessary.
- Tab completion uses a static copy of this machine's eza 0.23.5 colors for basic
  file kinds and common extensions: bold blue directories, plain ordinary files,
  green executables, cyan symlinks, and file-type colors. This is a snapshot,
  not automatic synchronization with future eza themes or every classification.
  It also has a highlighted selection menu and
  case-insensitive matching. Insecure
  completion directories are ignored by `compinit -i`, never blindly trusted.
  Restore `.zshenv` and `.zshrc` together: `.zshenv` disables Ubuntu's earlier
  global completion initialization so the completion cache can be reused.
  Windows command directories remain on PATH.
  See [startup profiling](ZSH_PROFILING.md) for measurements and reproduction
  commands; terminal timings and agent-environment timings are reported separately.
- When eza is installed, `ls` runs `eza`, `la` runs `eza -la`, and `ll` runs `eza -ll`.
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

### WSL browser helpers

Inside WSL (`WSL_DISTRO_NAME` is set), `edge <file>` and `chrome <file>` open one
existing local file in the corresponding Windows browser. For example:

```sh
edge "notes with spaces.md"
chrome report.html
```

Both call `_wsl_open_file`, which validates exactly one argument, resolves it
with `realpath -e --`, verifies it is a regular file, and converts it with
`wslpath -w`. Conversion failure stops the launch. Browser discovery first checks
PATH for `msedge.exe` or `chrome.exe`, then the standard installation directories
under `/mnt/c/Program Files` and `/mnt/c/Program Files (x86)`. For per-user or
custom installations, add the browser's application directory to PATH.

The helper passes the converted filename directly to the browser executable,
avoiding CMD's interpretation of `%`, `&`, and other filename characters.
It leaves the shell's working directory unchanged and starts the browser in the
background. Browser output is suppressed; success means launch was dispatched,
not that the browser finished loading the file. Windows/WSL interoperability
must be enabled. These helpers open files, not URLs, and do not render Markdown
themselves. Browser display behavior depends on the browser and its extensions.

Tool lookup and conversion happen only when a helper is invoked. Startup only
defines the functions; the existing PATH and completion audit policy remain.

### Other integrations

`.zshenv` quietly loads the readable Cargo environment and owns Zsh's base PATH.
Interactive Zsh adds the optional Neovim preference and initializes fnm, giving
this order when the corresponding directories and tools are installed:

```text
current fnm multishell/bin
/opt/nvim-linux-x86_64/bin
~/.cargo/bin
inherited Linux and Windows entries, in their original relative order
~/bin
~/.local/bin
```

PATH entries are unique; inherited managed entries are repositioned too.
`~/bin` and `~/.local/bin` are included only when present. `.profile` builds the
portable login environment with Cargo first, inherited entries next, then
`~/bin` and `~/.local/bin`, before sourcing Bash's interactive configuration.
Login normalization drops empty PATH components, which otherwise search the
current working directory, while preserving non-empty inherited ordering.
`.bashrc` provides guarded Cargo/local-bin fallbacks when those entries are
missing; it does not reorder arbitrary standalone Bash environments.

uv and uvx, Juliaup, and the Julia launcher are Cargo-managed and resolve from
`~/.cargo/bin`. Julia runtimes/state and optional completions remain under
`~/.julia/juliaup/`. Shell startup does not source the old `~/.local/bin/env` or
`env.fish` helpers or inject `~/.juliaup/bin`. Older installer-based machines
need to migrate their tools separately; these dotfiles do not install them.

fnm retains `--use-on-cd`. Startup generates its environment successfully before
removing prior absolute `fnm_multishells/<single directory>/bin` PATH entries and
applying the new environment. If generation fails, PATH at entry to fnm
initialization remains unchanged. Unrelated inherited directories are retained.

The native standalone Codex installation can use the generic `~/.local/bin`
entry for its symlink. No Codex-specific PATH block, installation, npm package,
or dependency requirement belongs to this configuration.

direnv, zoxide, Ubuntu's terminal-only fzf integration, Julia completions, and
Bash's broot integration remain optional. Generated Cargo environment files and
completion files are not backed up; regenerate them with the owning tools.

Install eza to enable the `ls`, `la`, and `ll` aliases. The dependency report
lists it as optional; missing eza leaves the system ls available.

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
