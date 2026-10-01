# Validation

## Selective restore and public maintenance — 2026-10-01

Repeatable `restore.py --file` arguments select exact entries from
`managed-files.txt`. Regressions cover one file and the future five-config
bootstrap selection, preview without writes, changes/backups limited to the
selection, duplicate deduplication in sorted order, and rejection of unknown,
unmanaged, or unsafe values before copying. They also verify both existing
profiles, exclusion of explicit `--profile` plus `--file`, managed-manifest
validation, source existence/type/symlink checks, destination conflicts and
overlap checks, file-symlink backups, and unchanged-file repeat behavior.

At this checkpoint the managed manifest contained nine configs and the public
allowlist contained 35 files. Public export regression checks verify exact
membership, documentation links, referenced tools, and private-file exclusion.
Current validation commands use `-B` to avoid bytecode caches that would block
public sync under its unchanged dirty/ignored-file policy:

```sh
DOTFILES_TEST_PLUGINS="${XDG_DATA_HOME:-$HOME/.local/share}/zsh/plugins" \
  python3 -B -m unittest discover -s tests -v
```

The complete suite passed in the private repository: **55 tests, no skips,
31.515 seconds**, with installed standalone plugins enabled. All 15 Python
scripts/test modules compiled; the four documented shell syntax checks and
`git diff --check` passed. The real public repository and live configs were not
modified, and no changes were staged, committed, or pushed.

## Test controlling-TTY isolation — 2026-10-01

The restore preview test reproduced a ten-second timeout when launched from a
disposable controlling PTY. Its interactive Zsh opened `/dev/tty` as fd 10,
claimed the terminal foreground group, displayed a prompt there, and waited
for input instead of consuming the test's pipe. The completion-cache test
passed without a controlling TTY but stopped with `SIGTTIN` when run in a
background group of a disposable PTY. Both tests passed in the earlier agent
environment because that environment had no controlling TTY.

The preview test now starts its subprocess in a new session while keeping its
piped commands. Captured Zsh probes use `/dev/null` stdin, a new session, and a
ten-second timeout. They retain interactive startup, the original global-rc
coverage, and all completion/cache assertions. Interactive editing tests still
use their own private `pty.fork()` sessions. Production shell configs and the
interactive preview command were not changed.

A regression reruns both affected tests in background groups of private PTYs,
checks for stopped processes and foreground-group changes, and rejects prompt
escape sequences leaking to the terminal. It failed for both original tests
before the fix and passes with the subprocess isolation in place.

The complete suite then passed with installed standalone plugins enabled:
**44 tests, no skips, 28.589 seconds**. This run used a background process group
attached to a disposable controlling PTY; its foreground group stayed with the
supervisor throughout. Python/shell syntax checks and `git diff --check` passed.

## Pre-push review fixes — 2026-09-17

- Restore and the comparison CLI now use the explicit nine-file
  `managed-files.txt` list. Generated completion caches and unrelated local
  files under `home/` are excluded. Restore preflight rejects missing managed
  sources and symlinked source paths before changing any destination.
- `scripts/preview_zsh.py` puts startup files and completion caches in a
  temporary ZDOTDIR and cleans it on normal exit. A real-shell regression
  confirms preview leaves the repository payload unchanged. A subsequent
  restore with deliberately planted caches still deploys exactly nine files.
- At the 2026-09-17 checkpoint, the public manifest contained 33 files, including profiling docs,
  benchmark tools, the preview helper, and a sanitized numeric evidence summary.
  Raw profiles, usernames, home paths, and command strings are excluded from
  that summary. Tests check exported documentation links, referenced scripts,
  config manifest consistency, absence of raw artifacts/personal home paths,
  and tool help commands. Summary timing samples were compared with the private
  raw inputs and are unchanged.
- Eza is reported as an optional dependency, with both missing and available
  fixture cases covered. Shell startup and the live configuration are unchanged.

All 27 tests passed both in the repository (26.558 seconds) and in a temporary
public export (26.563 seconds), with installed standalone plugins enabled.
After tightening the comparison check for a managed file replaced by a
directory, all four report tests passed again. Whitespace checks passed.
No commit amendment, staging, publication, or push was performed.

```sh
DOTFILES_TEST_PLUGINS="$HOME/.local/share/zsh/plugins" python3 -m unittest discover -s tests -v
git diff --check
python3 scripts/export_public.py --output ./public-export-review-20260917
```

Choose a new output directory if it already exists. Existing exports are not
overwritten. Public exports contain reviewed copies, not the private Git history;
new profiler output still requires separate review before publication.

## Shared WSL browser helper — 2026-09-17

Added `_wsl_open_file` with `edge()` / `chrome()` wrappers to the repository
configuration. It checks one existing regular file, uses `realpath -e --`, checks
conversion separately, and launches the browser executable directly. Browser
discovery supports PATH and the standard Program Files locations on drive C.
Both actual standard installations were found by read-only inspection on this
machine. Direct launching removes CMD parsing of the user-provided filename.
No browser discovery or external conversion is run during shell startup.

Executable fixtures exercise both wrappers with spaces, leading hyphens, and
`%TEMP%`, ampersands, and exclamation marks in filenames. Tests confirm the full
converted path is one argument, the caller's directory is unchanged, invalid
argument counts/missing files/directories/conversion failures do not launch, and
the helpers are absent outside WSL. The fixture tests exercise the shared shell
implementation without opening a browser. Real browser UI behavior and Windows
argument delivery remain a manual acceptance check.

Validation: all 25 tests passed in 25.996 seconds with the installed standalone
plugins enabled; `zsh -n home/.zshrc` and `git diff --check` also passed.

Live `.zshrc` activation remains separate; it still contains the original helper
definitions until the repository shell profile is restored.

## Startup profiling — 2026-09-17

See [the profiling report](ZSH_PROFILING.md) for the user's direct hyperfine
results, controlled temporary-config comparisons, section timings, and retained
raw evidence. Windows PATH lookup remains a major cost; completion initializes
once and reuses its warm cache. The decision is to keep the current startup
configuration unchanged.

## Operating system baseline

Ubuntu is the primary development target. The environment inspected on
2026-09-15 reports Ubuntu 26.04.1 LTS (`resolute`), x86_64, running kernel
`6.18.33.2-microsoft-standard-WSL2`, with Zsh 5.9 and Python 3.14.4.
These values were read from `/etc/os-release`, `uname -srm`, `zsh --version`,
and `python3 --version`.

The local shell, restore, and performance results below are evidence for this
Ubuntu/WSL2 environment. Native Ubuntu remains an intended target without a
separate validation run. Other Ubuntu releases, other Linux distributions,
architectures, native Windows, and macOS have not been qualified by these tests.
Windows Terminal appearance checks are separate from Linux shell behavior.
See [setup assumptions](SETUP.md#operating-system-and-environment) when reproducing
the results or adapting the configuration to another machine.

## Public snapshot preparation — 2026-09-15

Three public-preparation tests, six restore tests, and four report tests passed.
The public tests exercise optional local Git identity and override precedence in
an isolated HOME, shell-profile preview/apply and backups, private-file exclusion
from restore/comparison, Git ignore behavior, and explicit export membership.

```sh
python3 -m unittest discover -s tests -p test_public_preparation.py -v
python3 -m unittest discover -s tests -p test_restore.py -v
python3 -m unittest discover -s tests -p test_reports.py -v
```

At that checkpoint, the public list contained 27 files, with the historical shell reference omitted.
A scan of those selected files found no known personal name/email/account values
or common private-key/GitHub/OpenAI token formats. Git identity was removed from
the shared config; an autogenerated Zellij comment containing a personal home
path was removed. This scan supplements review, not a guarantee for future edits.
The exported tree contains exactly the manifest files, with no `.git`, reference
copy, or local identity file. Git whitespace checks pass.

A sanitized snapshot is prepared; no public repository has been created or
published. Existing history and live home configs remain untouched. Bootstrap
implementation and choice of public URL/commit identity remain user-owned steps.

## Transient redraw regression — 2026-09-15

The reported missing collapse was reproduced in a clean PTY: Enter cleared the
prompt area but redrew the complete Starship prompt before executing the command.
The hook's local PROMPT/RPROMPT bindings expired before ZLE performed its redraw.
A fixture changing only their lifetime reproduced the expected collapsed arrow.

The fix retains the transient values until a precmd hook restores the saved
full prompt. That hook follows Starship's status capture; it does not rewrite
previous command output or compute an exit status for the collapsed arrow.

The new regression test failed before the fix. It inspects redraw output before
a distinct command-output marker, requiring an arrow without the full prompt's
opening segment, then requiring the full prompt after command output. It repeats
the command and runs with standalone plugins when provided. The earlier test
that inspected PROMPT during command execution was replaced with a check of
the next rendered prompt: while a command executes, PROMPT is now transient.

All six Zsh tests passed with the standalone plugins, including the new redraw
regression, actual exit statuses, Ctrl+C, multiline input, and fixed arrow colors.
Command: `DOTFILES_TEST_PLUGINS=/tmp/dotfiles-plugin-validation/plugins python3 -m unittest discover -s tests -p test_zsh.py -v`.
Zsh syntax and Git whitespace checks also passed. Live configs were not changed.

## Read-only reports — 2026-09-15

Four new report tests and all six restore tests passed:

```sh
python3 -m unittest discover -s tests -p test_reports.py -v
python3 -m unittest discover -s tests -p test_restore.py -v
```

Fixtures cover controlled executable discovery, configured-path mismatches,
XDG plugin locations, missing integrations, comparison statuses, binary diff
suppression, unified diff labels, read errors, source symlink rejection, exit
codes, exclusion of unrelated files, and unchanged fixture contents.

Both commands were also run against this machine without `--diff`: dependency
report completed successfully; comparison reported five different and four
identical files (exit 1 as documented). The standalone plugin paths were missing;
no installation or restoration was performed. Shell/plugin tests were not rerun
because this addition does not change their configuration or implementation.

## Restore from a repository under HOME — 2026-09-15

The former overlap check rejected the normal repository-under-home layout.
Restoration now permits that layout while rejecting targets inside the repository
and individual destination paths that would overwrite repository contents.
All destination checks run before copying.

The new regression test failed before the fix and passed afterward. All six
restore tests pass, including default-HOME preview/apply with the repository
nested under `project/dotfiles`, preservation of repository bytes and existing
config backups, and rejection of a payload targeting repository contents before
any files are copied. `python3 scripts/restore.py` now previews the real home
successfully. No apply was performed against the real home. `git diff --check`
also passes. Unrelated shell/plugin tests were not rerun for this restore-only fix.

## Fixed-color arrows — 2026-09-15

All 10 unittest cases passed, including the installed-plugin checks, with:

```sh
DOTFILES_TEST_PLUGINS=/tmp/dotfiles-plugin-validation/plugins python3 -m unittest discover -s tests -v
zsh -n home/.zshrc
git diff --check
```

- Transient rendering is identical for statuses 0, 1, and 130 in Emacs, Vi insert,
  command, replace-one, replace, and visual keymaps. ANSI color output is checked
  against the existing green palette and the regular character module.
- PTY tests verify actual `$?` values after success (0), failure (1), and
  interruption (130), using output markers that differ from echoed commands.
- Logged transient renderer calls contain no status or duration arguments.
- Full prompt restoration, empty Enter, Ctrl+C, and multiline input still pass.
- TOML parsing, Zsh syntax, and Git whitespace checks pass.

Both arrow types now mark input with fixed green color. They do not indicate
command results. Starship's normal initialization and Zsh status handling remain
in place; no post-command cursor movement was added. Live files and the
historical reference were not changed.

## Framework-free Zsh implementation — 2026-09-14

Validated on Zsh 5.9 and Starship 1.25.1. Nine unittest cases passed, including
all optional standalone-plugin checks, using:

```sh
python3 scripts/install_zsh_plugins.py --target /tmp/dotfiles-plugin-validation/plugins
DOTFILES_TEST_PLUGINS=/tmp/dotfiles-plugin-validation/plugins python3 -m unittest discover -s tests -v
python3 scripts/install_zsh_plugins.py --target /tmp/dotfiles-plugin-validation/plugins
zsh -n home/.zshrc
zsh -n home/.zshenv
```

- Restore preview, backups, repeated runs, conflict preflight, and file-symlink
  preservation passed in disposable homes.
- Plugin installer tested with local fixture repositories: successful install,
  clean rerun, modified/mismatched destination refusal, failed fetch cleanup.
- The real installer fetched all three pinned public upstream revisions into
  temporary storage. A second run reported all three unchanged. Initial sandbox
  DNS failure was followed by a successful network-enabled run.
- Minimal shell startup passed without Starship/plugins, with no stderr.
- PTY checks passed for shared history across two shells, Tab completion,
  autosuggestion display, substring history search, and plugin widget loading.
- Starship PTY checks passed for failed-command status, full prompt retention,
  empty Enter, cancelling input, interrupted-command status 130, and Shift+Enter
  multiline input. The code does not install a global Ctrl+C trap.
- Starship TOML parsed; full prompts rendered without warnings inside/outside
  a temporary Git repository for exit statuses 0, 1, and 130.
- An fzf warning discovered in non-TTY interactive startup was fixed by guarding
  its terminal integration. The complete test suite passed after that change.

The normal test command skips the real-plugin case unless DOTFILES_TEST_PLUGINS
is set, and skips the Starship case if its executable is unavailable. Tests use
Python's standard library and do not download dependencies automatically.

Visual acceptance still requires the user's terminal: Nerd Font glyphs, color
appearance, transient redraw appearance, syntax-highlight colors, and the
terminal's actual Shift+Enter mapping. PTY tests exercise escape sequences and
shell behavior but do not replace viewing the terminal. Full developer-tool
installation and recovery on another physical machine remain untested.

## Completion highlighting and startup performance — 2026-09-15

The live baseline matched the repository configuration except for commented
profiling lines. The original backup was `~/zshrc_backup_20260915` (no leading
dot). Its Oh My Zsh completion library enabled `zsh/complist` and
`zstyle ':completion:*' list-colors ''`; these native settings restore the
directory colors without an eza dependency. The existing menu selection remains.

### Root cause and change

- Ubuntu's `/etc/zsh/zshrc` called `compinit` before the user's `.zshrc` called it
  again. The first call found 1,005 completion files; adding the 15 files under
  `~/.zfunc` made the second find 1,020. Both calls rewrote the same dump on each
  startup. Profiling from `.zshrc` alone missed the first call.
- The interactive `.zshenv` now sets Ubuntu's `skip_global_compinit=1` switch.
  `.zshrc` still calls `compinit -i` after extending fpath. Security auditing is
  retained on every startup; no `-C` or audit-bypass policy was introduced.
- Zsh command-table access scanned the inherited Windows PATH directories,
  including inside `compaudit`. Standalone `$+commands[...]` probes took about
  180–230 ms during diagnosis. Replacing optional-tool checks with quiet
  `command -v` avoids additional full-table population after PATH changes.
  All Windows PATH entries are retained. The remaining audit/lookup cost is
  accepted; a Linux-only diagnostic reached ~50 ms but changes command access.

### Reproduction and measurements

Run from a Git checkout with the normal inherited PATH and installed tools.
`HEAD` compares the working tree with its current commit; choose an available
earlier local revision to compare against a different baseline. Historical
private commit IDs are not included in the public snapshot's fresh history:

```sh
python3 scripts/benchmark_zsh.py --baseline-ref HEAD --runs 5
```

The script executes trusted baseline and working-tree startup configurations in
separate temporary ZDOTDIRs, retaining the real HOME, plugins, and PATH. It gives
fnm a temporary runtime directory, avoiding the sandbox's read-only runtime
directory. It measures non-TTY `zsh -i -c exit`, starting without a completion
dump, then repeating with that dump. A separate run profiles from `.zshenv` so
global initialization is included. Temporary benchmark files are removed.

Measured with Zsh 5.9 on this Ubuntu/WSL environment:

| Configuration | Missing-dump startup | Warm median | Warm compinit / compdump calls |
| --- | ---: | ---: | --- |
| Historical pre-fix baseline | 1,001.66 ms | 991.25 ms | 2 / 2 |
| Updated working tree | 511.43 ms | 299.64 ms | 1 / 0 |

Baseline warm samples (ms): 997.01, 991.25, 996.37, 981.73, 933.68.
Updated warm samples (ms): 265.61, 259.44, 314.73, 299.64, 316.07.
The warm median improved about 70%. Warm `compaudit` profiler counts changed
from four to two: its wrapper calls its internal implementation, so two profiler
entries represent one audit invocation from compinit.

These measurements exclude time to draw the first prompt and TTY-only fzf
integration. They are local observations, not a cross-machine timing guarantee
or a filesystem-cold benchmark. No timing threshold is asserted in unit tests.

### Regression validation and activation

```sh
DOTFILES_TEST_PLUGINS="$HOME/.local/share/zsh/plugins" python3 -m unittest discover -s tests -v
zsh -n home/.zshrc
zsh -n home/.zshenv
git diff --check
```

The added cache test includes the global zshrc and checks one initialization,
custom completion registration, unchanged warm cache, continued auditing, and
rebuilding after a completion file is added. Another test verifies insecure
completion directories are ignored. PTY checks exercise colored directory names,
reverse-video selection, Tab cycling, and accepting the selected directory.
Tool fixtures verify optional integrations load and inherited Windows PATH
entries survive. Existing minimal-shell, plugin, history, and prompt checks run
alongside these tests.

Final result: all 24 tests passed in 23.827 seconds, including the installed
standalone-plugin cases. Both Zsh syntax checks and `git diff --check` passed.

Before the configuration change, the new tests reproduced two compinit calls
and missing directory colors. While developing the PTY test, its initial blue
color assumption and single-Enter command execution assumption were corrected:
Zsh emitted red directory names, and Enter accepts menu selection before a
second Enter executes the command. These were test-harness corrections.

Live configuration activation is separate. Preview confirmed Starship was
identical and only `.zshenv` and `.zshrc` would be replaced:

```sh
git diff -- home/.zshenv home/.zshrc
python3 scripts/restore.py --profile shell
python3 scripts/restore.py --profile shell --apply
exec zsh
```

Run the apply step when ready, keeping another terminal open. The restore script
backs up replaced files; both Zsh files must be activated together. Actual color
appearance still needs visual confirmation in the user's terminal.

## Eza palette and aliases — 2026-09-15

The installed eza is 0.23.5, with no `LS_COLORS`, `EZA_COLORS`, or custom eza
theme in the inspected environment. A temporary fixture listing using
`eza -1 --color=always --icons=never` confirmed bold blue directories, plain
ordinary files, bold green executables, and cyan symlinks. Comparison of 68
representative extension/build filenames caught `.tsx` being plain in this
version; its proposed source-color mapping was removed.

The completion palette now contains static basic-kind and common-extension
rules matching those observations, plus common build filenames. It does not
invoke eza at startup or alter eza's own colors. This is a snapshot, not complete
emulation of every eza filename classification or automatic theme syncing.
Eza has its own extension and theme rules; see the upstream
[color documentation](https://github.com/eza-community/eza/blob/v0.23.5/man/eza_colors.5.md).
Reverse-video menu selection remains enabled.

When eza is available, the requested aliases are `ls='eza'` and `la='eza -la'`.
Without it, the aliases are not installed and the system ls remains available.

All 10 shell tests passed with installed standalone plugins (24.569 seconds),
including updated PTY assertions for blue directories and source/image/archive
colors, selection cycling, and executable-fixture checks for both aliases.
`zsh -n home/.zshrc` and `git diff --check` passed.

The benchmark against `c2b66891f98aa130b2843f1924ec0a321f73b27f` observed warm
medians of 342.14 ms before and 354.36 ms after (five runs each, while the shell
suite was also running). This is a coarse regression check, not an isolated
estimate of palette overhead. Both profiles retained one compinit and zero warm
compdump calls. Reproduce with:

```sh
python3 scripts/benchmark_zsh.py --baseline-ref HEAD --runs 5
DOTFILES_TEST_PLUGINS="$HOME/.local/share/zsh/plugins" python3 -m unittest discover -s tests -p test_zsh.py -v
```

Live activation remains separate. Restore preview reports only `.zshrc` changed;
`.zshenv` and Starship match. Use the shell-profile activation commands above.

## Backup scope

Nine configs remain in the restore payload. Fish helpers and terminal monitors
were removed by request. Starship's layout and unrelated app settings
were preserved; arrow colors were updated on 2026-09-15. The previous project Zsh config is retained under `reference/`
and is not restored. Live home configs were not changed; no project Git staging,
commits, or publishing were performed.

Earlier snapshot checks parsed Git config and Mermaid JSON and found no common
secret-pattern matches in the captured configs. Review contents, especially Git
identity, before publishing. The backup excludes credentials and downloaded
plugin repositories.
