# Zsh startup profiling — 2026-09-17

This report describes the configuration and inherited PATH measured on
2026-09-17. The [2026-10-05 PATH cleanup](VALIDATION.md#cargo-ownership-and-wsl-path-cleanup--2026-10-05)
changed startup configuration; these performance measurements have not been
rerun against that state. See [setup notes](SETUP.md#other-integrations) for
current PATH and tool ownership.

## Decision

Keep the current startup configuration, Windows PATH access, and completion
security checks. This investigation adds measurements and reproduction tooling;
it did not change the live or repository `.zshrc` / `.zshenv` files. At measurement
time, the live configuration included the user's duplicated `edge()` and
`chrome()` helpers, absent from the repository configuration. The shared helper
was implemented afterward; these timings describe the recorded inputs, not a
new benchmark of that implementation. No browser was launched during profiling.

## User's direct terminal measurements

The user supplied these hyperfine results from the normal terminal:

```sh
hyperfine --warmup 5 'zsh -i -c exit' 'zsh -o no_global_rcs -i -c exit' 'zsh -f -i -c exit'
```

| Command variant | Mean ± standard deviation | Range | Runs |
| --- | ---: | ---: | ---: |
| Normal interactive startup | 450.8 ± 67.5 ms | 395.8–636.3 ms | 10 |
| `no_global_rcs` | 498.1 ± 60.4 ms | 431.2–576.2 ms | 10 |
| `-f` | 1.1 ± 0.2 ms | 0.8–3.1 ms | 1,848 |

These are the best available observations of the user's normal terminal startup.
They do not show a benefit from disabling global startup files.

## Controlled agent measurements

[The profiler](../scripts/profile_zsh.py) copies the live configs into temporary
ZDOTDIRs. It preserves real HOME and installed integrations, while redirecting
completion dumps and fnm runtime writes. Each variant gets a separate dump,
one startup sanity check, five hyperfine warmups, and ten measured runs.
Measurements are sequential, without a concurrent test suite.

| Temporary variant | Mean ± standard deviation |
| --- | ---: |
| Current configuration, inherited PATH | 628.6 ± 42.9 ms |
| Same configuration, `no_global_rcs` | 545.8 ± 46.4 ms |
| `-f` | 1.2 ± 0.1 ms |
| Current configuration, PATH entries under `/mnt/` removed | 44.1 ± 2.4 ms |

The inherited PATH contained 53 entries, 36 under `/mnt/`. Removing these is a
diagnostic intervention only. It changes command availability, including the
`cmd.exe` guard for browser helpers. It is not a proposed deployment change.

The agent environment, temporary paths, process scheduling, and filesystem cache
state differ from the normal terminal. Do not replace the user's 450.8 ms figure
with the agent's 628.6 ms figure or interpret their difference as a regression.
The variants were measured in fixed order; these are not randomized trials.
The global-file comparison also goes in the opposite direction to the user's
run, so it does not justify removing global initialization.

## Where time is spent

Separate instrumented runs used Zsh's `EPOCHREALTIME` around configuration
sections, with `zprof` enabled from `.zshenv` before global Zsh startup. These
profiling runs are excluded from the hyperfine timing samples.

Median section times across three instrumented runs:

| Section | Inherited PATH | Diagnostic Linux-only PATH |
| --- | ---: | ---: |
| Completion initialization and styles | 411.2 ms | 22.0 ms |
| Optional integration checks and initialization, including browser definitions | 213.2 ms | 5.3 ms |
| Starship initialization | 5.3 ms | 5.9 ms |
| Autosuggestions and history plugin loading | 2.1 ms | 2.2 ms |
| Syntax highlighting setup | 4.4 ms | 4.8 ms |

The section figures describe other runs and should not be added to reconstruct
the hyperfine mean. Starship initialization excludes drawing the first prompt.

All nine warm profiles recorded **one compinit call and no compdump call**.
The cache-rebuild fix is intact. The two compaudit profiler entries are its
wrapper and internal call, not two independent completion initializations.

`compaudit` accesses `commands[getent]`. A separate fresh-shell probe of
`(( $+commands[getent] ))` took 344–363 ms with the inherited PATH versus
8–10 ms with the diagnostic PATH (three samples for each). Together with the
section timings, this supports Windows-directory command-table population and
lookup as a major cost. A large compaudit time does not mean all of that time
was spent checking completion-directory permissions.

The integration section was measured as a group; this run does not attribute
its entire cost to a specific tool. The Linux-only variant also changes which
optional commands are found. No specific Windows directory was identified as
the slowest. Neither 450.8 ms nor 44.1 ms is a guaranteed minimum.

## Evidence and reproduction

The [sanitized evidence summary](benchmarks/zsh-2026-09-17/summary.json) includes
numeric timing samples, section medians, lookup samples, config hashes, and
selected OS/tool versions. It excludes usernames, home paths, command strings,
and raw zprof output. Raw evidence is retained only in the private archive and
is not part of the public export. The report and both benchmark tools are exported.

From the repository root, choose a new output directory:

```sh
python3 scripts/profile_zsh.py --output /tmp/zsh-profile-repeat --warmup 5 --runs 10
```

The profiler requires installed `hyperfine` and `zsh`. It defaults to configs
from HOME; `--source /path/to/config-directory` selects another pair. Only run
trusted configs: startup code executes with the real HOME and installed tools.
The script refuses an existing output directory. It validates expected section
markers and fails if startup emits stderr, rather than silently measuring failed
initialization. Match source hashes in the summary when comparing reruns.
New profiler output contains local paths and is private until separately reviewed;
the public manifest includes only the reviewed summary from this recorded run.
Section profiling relies on the current configuration's comment markers.

All benchmark samples exited successfully, profile call counts were checked,
and the live config hashes were unchanged after the run. No configuration fix or
activation was performed. The measurements cover non-TTY `zsh -i -c exit`, not
first-prompt rendering, terminal-only fzf setup, browser startup, or Tab latency.

Future optimization would require another measured tradeoff, such as narrowing
Windows PATH access. There is no need to change the current setup solely because
the agent environment produces higher absolute timings.
