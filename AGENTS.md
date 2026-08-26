# AGENTS.md

Guidance for AI coding assistants (and humans) working in this repository.

## Overview

Two independent things live here:

1. **`Containerfile`** (+ `99-ai-container.conf`) — builds the *guest* container image (openSUSE Tumbleweed with Claude Code, OpenCode, and a pile of language toolchains/LSPs). Built with `podman build`/`container build`. Not a Python project; no build/test tooling applies to it beyond `podman build` itself.
2. **`src/ai_container/`** — the *host*-side launcher: a `uv`-managed Python CLI (Typer + Rich) that assembles and runs the `podman run`/`container run` invocation. This is what the rest of this file is about.

The launcher never talks to a container-engine daemon API directly — it only ever builds an argv list and executes `podman`/`container` as a subprocess, printing the exact command with `--debug`.

## Build / run / test commands

All commands run from the repo root, via `uv` (no need to activate a venv manually):

```bash
uv sync                       # install runtime + dev dependencies into .venv/
uv run ai-container --help    # run the CLI in place
uv run ruff format .          # format
uv run ruff check .           # lint (add --fix to auto-fix)
uv run mypy                   # strict type-check
uv run pytest                 # full test suite, with coverage report
uv run pytest tests/test_cli.py -k web  # run a subset
```

CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`, `mypy`, and `pytest` on every push/PR. Keep all four green before considering work done.

Git hooks are config-driven (`.githooks.config`, Git ≥2.55's `hook.<name>.*`); see the "Development" section of `README.md` for the one-time opt-in command. If they're enabled locally, `git commit`/`git push` run the same checks as CI.

## Project structure

```
src/ai_container/
  cli.py         Typer app: option parsing, orchestration, the "wrapper opts -- tool args" split
  console.py     Rich-backed Reporter (✓/✗/▶ output, gated debug lines)
  engine.py      podman/`container` engine selection + per-engine argument differences
  models.py      Engine enum, MountSpec/MountKind/MountAccess dataclasses
  paths.py       host<->container path remapping, $HOME-as-workdir guard
  git_utils.py   git worktree detection
  selinux.py     sestatus parsing + the :z/:Z suffix rules
  mounts.py      the declarative table of ~20 conditional credential/cache mounts
  ssh_agent.py   SSH agent forwarding + the `container --ssh` rootless relay chmod workaround
  web.py         --web mode (random password, host IP detection, banner)
  naming.py      random container names / web passwords
  runner.py      final argv assembly + subprocess execution + `stty sane` cleanup
  rich_patches.py  strips typer's Rich help/error box borders while keeping color (see its docstring)
tests/           one test module per src module, plus tests/test_cli.py for end-to-end CLI behavior
```

## Code style

- Small, single-purpose modules over one big script — this rewrite specifically replaced ~20 copy-pasted "if directory/file exists, mount it" bash blocks with one declarative `MountSpec` table (`mounts.py`) plus a single `apply_mount()`. Keep new mounts/features that fit this shape declarative rather than adding another bespoke `if` block.
- Prefer pure functions that take explicit parameters (`host_home`, `container_home`, `host_platform`, ...) over reading global state, so they stay trivially testable.
- Keep comments terse; only add them where the *why* isn't obvious from the code (e.g. the SELinux `:z`/`:Z` suffix rules, the `container --ssh` root-owned relay socket workaround).
- Full type hints everywhere; `mypy --strict` must pass with zero ignores added without a comment explaining why.
- Ruff is configured with security-lint rules (`S`) enabled, since this tool's entire job is spawning subprocesses with host-derived paths. `S603`/`S607` are ignored project-wide (that's the point of the tool); don't blanket-ignore new rule categories without discussing it in the PR description.

## CLI argument parsing

`cli.py`'s `app` sets `context_settings={"ignore_unknown_options": True}`. This makes Click keep scanning the whole command line for options it recognizes rather than erroring out (or stopping, bash-style) on the first one it doesn't — any option-looking token we haven't defined (`-c`, `--resume`, ...) is forwarded straight through to `tool_args` without needing `--` first. `--` is still required, and still supported, when a tool argument's name collides with one of `ai-container`'s own flags (or with `-h`/`--help`), since those are always claimed by us first regardless of position. See the "Basic usage" section of `README.md` for examples.

Consequence for future changes: every new flag (especially short ones) added to `main()` becomes a new potential collision point that then requires `--` to work around. Prefer long, distinctive flag names; think twice before adding more short aliases beyond `-h`.

## Testing notes

- `tests/conftest.py` provides `isolated_home` (fresh `$HOME` via `tmp_path`), `workdir` (a cwd outside `$HOME`), and `fake_engine_path` (stub `podman`/`container` executables on `$PATH`) — use these instead of touching the real host environment.
- External commands (`sestatus`, `git`, `podman`/`container exec`, `hostname -I`, `ipconfig`) are faked with `pytest-subprocess`'s `fp` fixture rather than mocking our own wrapper functions, so tests exercise the real subprocess-argument-building code.
- `tests/test_git_utils.py` uses real `git init`/`git worktree add` calls against `tmp_path` rather than mocking git output — prefer that pattern when it's cheap, it catches real git behavior changes.
- `tests/test_cli.py` uses Typer's `CliRunner` end-to-end, with `ai_container.cli.run` monkeypatched to a spy that captures the final argv instead of actually invoking a container engine.
- Pure/parsing-only functions (`paths.map_to_container_path`, `naming.*`) have `hypothesis` property tests alongside the example-based ones.

## Non-goals / known constraints

- Docker isn't implemented (`models.Engine` only has `PODMAN`/`CONTAINER`). The code is structured so adding it means adding one enum member plus one branch per function in `engine.py`, not a rewrite.
- The bash-era quirk where read-only `-v` mounts get the private `:Z` SELinux label while read-write `-v` mounts and all `--mount=type=bind` mounts get the shared `:z` label is preserved intentionally (see `selinux.py` docstring) — it was ported faithfully, not redesigned.
