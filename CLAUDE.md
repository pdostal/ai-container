# CLAUDE.md

This file provides guidance to AI coding assistants (Claude Code, OpenCode) when working with code in this repository.

## Overview

This repository contains a Containerfile that defines AI Coding Assistants container environment. Changes here affect the runtime environment.

## Build

```bash
podman build -t ai -f Containerfile .
```

Also buildable with Apple's `container` tool on macOS (`container build -t ai -f Containerfile .`).

## Run

Use `./ai-container` script for the full setup with credentials and agent forwarding. It supports both `podman` and macOS's native `container` runtime (auto-detected, or forced via `--runtime`/`AI_CONTAINER_RUNTIME`); see `README.md` for the differences between the two.

## Code Quality

- Always run `shellcheck` on shell scripts after making changes to ensure code quality and catch common issues.
