# Claude Code Container

Containerized AI Coding Assistants environment based on openSUSE Tumbleweed.

## Prerequisities

```bash
sudo transactional-update pkg install crun libkrun1 libkrunfw5 slirp4netns
```

## Build

```bash
podman build -t ai -f Containerfile .
```

## Run

```bash
./ai-container
```

The `ai-container` script automatically:
- Mounts the current directory as `/workdir`
- Configures SELinux labels when needed
- Forwards SSH agent for git operations
- Forwards GPG agent for signing
- Mounts credentials read-only (GitHub CLI, Git config, SSH known_hosts, OSC config)
- Mounts Claude configuration for persistence
- Optionally mounts Google Cloud credentials when available

## Included Tools

- **Git ecosystem**: git, git-lfs, gh, glab, gitea-tea
- **Python**: python3, uv, ruff, flake8, yamllint
- **Perl**: perl, perltidy
- **Linters**: shellcheck, markdownlint-cli
- **Node.js**: npm, npx
- **Security**: gpg2, openssh-clients
- **Utilities**: bat, less, cnf, command-not-found
- **OBS/OSC**: osc, obs-service-*, osc-plugin-qam
- **Claude Code CLI**

## Custom Entrypoint

You can specify a custom entrypoint instead of Claude Code:

```bash
./ai-container /bin/bash
```
