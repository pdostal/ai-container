# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

See [`AGENTS.md`](AGENTS.md) for the full project overview, build/test/lint commands, project structure, and code style — it's the canonical doc, kept in sync for every AI assistant (Claude Code, OpenCode, etc.).

## Containerfile quick reference

The `Containerfile` builds the *guest* AI Coding Assistants container image (independent of the Python launcher in `src/ai_container/`):

```bash
podman build -t ai -f Containerfile .
```

Also buildable with Apple's `container` tool on macOS (`container build -t ai -f Containerfile .`).

## Code quality

- Python changes: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy`, `uv run pytest` (see `AGENTS.md`).
- Shell scripts (`Containerfile` is not shell, but any `.sh` files added under it should be): always run `shellcheck` after making changes.
