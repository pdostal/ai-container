# AI Container

Containerized AI Coding Assistants environment based on openSUSE Tumbleweed. Supports Claude Code and OpenCode.

## Prerequisities

```bash
sudo transactional-update pkg install crun libkrun1 libkrunfw5 slirp4netns
```

## Build

```bash
podman build --build-arg CODER_UID="$(id -u)" --build-arg CODER_GID="$(id -g)" -t ai -f Containerfile .
```

The image creates a `coder` user with UID/GID `1000:1000` by default. Pass `CODER_UID` and `CODER_GID` when your host UID/GID differ, or when running through the Podman macOS VM. Rebuild the image if the host UID/GID you want to use changes.

## Run

```bash
./ai-container
```

The `ai-container` script automatically:
- Mounts the current directory as `/workdir`
- Uses `/home/coder` as the container home
- Mounts configuration from the host home directory into `/home/coder`
- Runs as the image's `coder` user
- Configures SELinux labels when needed
- Forwards SSH agent for git operations
- Forwards GPG agent for signing
- Mounts credentials read-only (GitHub CLI, Git config, SSH known_hosts, OSC config)
- Mounts AI assistant configurations for persistence (Claude Code, OpenCode)
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
- **AI Coding Assistants**: Claude Code, OpenCode

## Custom Entrypoint

You can specify a custom entrypoint using the `--entrypoint` flag:

```bash
# Run bash instead of the default entrypoint
./ai-container --entrypoint /bin/bash

# Run a command with arguments
./ai-container --entrypoint /bin/echo hello world

# Pass arguments to the default entrypoint
./ai-container --help
```
