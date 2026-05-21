# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository contains a Containerfile that defines AI Coding Assistants container environment. Changes here affect the runtime environment.

## Build

```bash
podman build -t ai -f Containerfile .
```

## Run

Use `./ai-container` script for the full setup with credentials and agent forwarding.

## Code Quality

- Always run `shellcheck` on shell scripts after making changes to ensure code quality and catch common issues.
