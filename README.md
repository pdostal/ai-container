# AI Container

Containerized AI Coding Assistants environment based on openSUSE Tumbleweed. Supports Claude Code and OpenCode, launched through a small `uv`-managed Python CLI that drives Podman, Docker, or Apple's `container` tool.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Build the container image](#build-the-container-image)
- [Install the launcher](#install-the-launcher)
- [Usage](#usage)
  - [Basic usage](#basic-usage)
  - [Web mode](#web-mode)
  - [Custom mounts](#custom-mounts)
  - [Workspaces](#workspaces)
  - [Vertex AI](#vertex-ai)
  - [Custom /etc/hosts entries](#custom-etchosts-entries)
  - [Custom entrypoint](#custom-entrypoint)
- [Configuration file](#configuration-file)
- [What the launcher does](#what-the-launcher-does)
- [Network configuration](#network-configuration)
- [Included tools](#included-tools)
- [Agent Skills](#agent-skills)
- [Development](#development)

## Prerequisites

```bash
sudo transactional-update pkg install crun crun-krun libkrun1 libkrunfw5 slirp4netns
```

Alternatively, Docker (Engine, rootless Engine, or Docker Desktop) works with no extra packages.

On macOS, you need [Podman](https://podman.io) (running via `podman machine`), [Docker Desktop](https://www.docker.com/products/docker-desktop/), or Apple's native [`container`](https://github.com/apple/container) tool (Apple silicon, macOS 26+). For `container`, install it and start its services once:

```bash
container system start
container builder start
```

The launcher itself is a Python CLI run through [`uv`](https://docs.astral.sh/uv/). Install `uv` (see its [installation docs](https://docs.astral.sh/uv/getting-started/installation/)); it manages its own Python interpreter, so no separate Python install is required on the host.

## Build the container image

```bash
podman build --pull=always --build-arg CODER_UID="$(id -u)" --build-arg CODER_GID="$(id -g)" -t ai -f Containerfile .
```

With Docker (the image tag `ai` is what the launcher runs):

```bash
docker build --pull --build-arg CODER_UID="$(id -u)" --build-arg CODER_GID="$(id -g)" -t ai -f Containerfile .
```

For rootless Docker the build-args don't matter (see [below](#what-the-launcher-does)). Or with Apple's `container` tool:

```bash
container build --pull --build-arg CODER_UID="$(id -u)" --build-arg CODER_GID="$(id -g)" -t ai -f Containerfile .
```

The image creates a `coder` user with UID/GID `1000:1000` by default. Pass `CODER_UID` and `CODER_GID` when your host UID/GID differ, or when running through the Podman macOS VM. Rebuild the image if the host UID/GID you want to use changes.

## Install the launcher

From a checkout of this repository:

```bash
uv tool install .
```

This puts an `ai-container` command on your `$PATH` (via `uv tool`'s shim directory). Upgrade after pulling changes with `uv tool upgrade ai-container`, or reinstall with `uv tool install --reinstall .`.

While developing the launcher itself, run it in place instead, without installing:

```bash
uv run ai-container ...
```

## Usage

### Basic usage

```
ai-container [WRAPPER OPTIONS] -- [TOOL ARGS]
```

Everything before `--` configures the launcher itself (engine, mounts, web mode, ...). Everything after `--` is passed straight through to the entrypoint running inside the container (OpenCode, Claude Code, or whatever `--entrypoint` points at).

`--` is only *required* when the tool argument you're forwarding collides with one of the launcher's own flag names (see the list in `ai-container --help`) or with `-h`/`--help`. The CLI is built with Click/Typer's `ignore_unknown_options`, so it keeps scanning the whole command line for flags it recognizes rather than stopping at the first one it doesn't — any other option-looking token (`-c`, `--resume`, ...) is forwarded to the entrypoint automatically, no `--` needed:

```bash
ai-container
ai-container --claude
ai-container --claude --resume              # --resume isn't ours, forwarded automatically
ai-container --entrypoint /bin/bash -c 'echo hi'   # same for -c
ai-container --claude -- --debug            # --debug *is* ours; -- forwards the literal flag instead
ai-container --extra-env MY_VARIABLE              # forward a host environment variable when set
ai-container --extra-env 'X=${HOME}/y'            # set a variable, expanding host variables
```

This is a deliberate (and arguably improved) departure from the old bash script's parsing, which stopped recognizing its own flags entirely as soon as it saw the first argument it didn't understand. Since `ai-container` keeps recognizing its own flags anywhere on the command line, only genuine name collisions need `--`.

Run `ai-container --help` for the full, coloured option reference.

The launcher automatically:

- Picks a container runtime: `podman` by default, then Apple's `container` on macOS, then `docker`. Override with `--runtime podman|container|docker` or the `AI_CONTAINER_RUNTIME` environment variable.
- Optionally runs the container inside a KVM microVM instead of plain namespaces, via crun's `krun` OCI runtime. Enable with `--microvm` (podman only; needs the `crun-krun` package and `/dev/kvm` access).
- Mounts the current directory at the same absolute path inside the container, so `pwd` matches on both sides. If it's under your host `$HOME`, it's remapped onto `/home/coder` instead (e.g. host `~/external/ai-container` → container `/home/coder/external/ai-container`), so `~`-relative paths line up too. Refuses to run if the current directory is your entire `$HOME`.
- Detects if the current directory is a git worktree and automatically rw-mounts the parent checkout (the repo containing the real `.git` directory) at the equivalent container path. Disable with `--no-worktree-mount`.
- Uses `/home/coder` as the container home.
- Runs as the image's `coder` user (podman: via `--userns=keep-id`; `container` and rootful docker: via `--uid`/`--gid` or `--user` matching the host user; rootless docker, detected with `docker info`: as container uid 0, which the daemon maps to your unprivileged host user so bind mounts stay writable).
- Configures SELinux labels when needed (podman/Linux: `:z`/`:Z` mount labels; docker: `--security-opt label=disable`, so host files are never relabeled).
- Forwards SSH agent for git operations unless disabled with `--no-ssh-agent` / `ssh_agent = false` (podman and docker: Linux only, by mounting the socket; Docker Desktop on macOS: via its `/run/host-services/ssh-auth.sock` relay; `container`: via its built-in `--ssh` forwarding, macOS only).
- Mounts `~/.ssh/known_hosts` read-only, and read-write `~/.claude`, `~/.claude.json`, `~/.config/opencode`, `~/.local/share/opencode`, `~/.local/state/opencode` and `~/.cache/opencode` (all skippable with `--disable-mount` / `disable_mounts`).
- Sets up [Vertex AI](#vertex-ai) from three host variables.
- Mounts and forwards nothing else by default: other credentials, tool configs, caches and environment variables come from the [configuration file](#configuration-file) (`extra_mounts`, `extra_envs`). Mounts only happen if the host path exists (a `✗ ... not found` line is printed with `--debug` otherwise); the container runs with `--rm`, so create directories such as `~/.local/share/opencode` on the host first if you want data like OpenCode session history to persist.
- Assigns a random container name (e.g. `ai-x7q`) printed on every run.

> [!NOTE]
> `--microvm` is new and only lightly tested: it adds `--annotation krun.use_passt=1` so pasta networking (see [Network Configuration](#network-configuration)) routes into the guest microVM, but this hasn't been verified on real hardware. If host-bound services aren't reachable from inside a `--microvm` container, that annotation is the first thing to check.

> [!NOTE]
> GPG agent forwarding isn't supported: Apple's `container` tool can't bind-mount a host AF_UNIX socket file into its VM (the socket node isn't accessible through its virtiofs share), so signing commits with a forwarded host agent doesn't work from inside the container on either runtime.

> [!NOTE]
> `container`'s `--ssh` forwarding always creates its relay socket owned by `root` inside the guest, regardless of `container` version ([apple/container#580](https://github.com/apple/container/issues/580) only made the guest copy inherit the host socket's exact mode bits, not its ownership). Since we run as the non-root `coder` user (see above), the launcher works around this by backgrounding a `chmod 0666` on that per-container relay socket (via `container exec -u root`, retried for up to 2s while the container boots). This only loosens the ephemeral, per-container copy of the socket living in that container's own private VM, not your real host `ssh-agent` socket.

### Web mode

Run OpenCode as a background web server:

```bash
ai-container --web
```

The container runs detached. The web interface URL, username, and password are printed on startup.

Additional web options:

| Flag | Default | Description |
|---|---|---|
| `--web-port PORT` | `4996` | Port to expose the web interface on (config: `web_port`) |
| `--web-username USER` | `coder` | HTTP basic auth username (config: `web_username`) |
| `--web-password PASS` | *(random)* | HTTP basic auth password (config: `web_password`) |

The flags override the config keys. A password from the config file is printed as `*****` at startup.

### Custom mounts

Bind-mount additional host directories or files into the container, in addition to the current directory and any auto-detected git worktree parent. The format is `SOURCE[:TARGET][:ro|rw]` (read-write by default):

```bash
ai-container --extra-mount ~/repos/b
```

`-m` is a shorthand for `--extra-mount`. Repeatable:

```bash
ai-container -m ~/repos/b -m ~/repos/shared-libs:ro -m ~/notes:/opt/notes:ro
```

Without `TARGET`, paths follow the same `$HOME`-remap rule as the workdir mount; `TARGET` must be absolute. On a target clash the first mount wins (workdir, then CLI, config, workspace dirs, worktree parent, built-in defaults, `known_hosts`), so a clashing mount is skipped automatically.

The old `--mount-extra` and `--env` spellings no longer exist; because unknown options are forwarded, they now reach the assistant as ordinary arguments.

### Workspaces

Named groups of directories, defined in the [configuration file](#configuration-file), that get mounted together in one shot instead of listing them all with repeated `--extra-mount` flags:

```bash
ai-container --workspace frontend
```

`--workspace` always looks the name up in the config file's `[[workspace]]` entries, regardless of `auto_workspaces`, and errors out if it isn't defined. With `auto_workspaces = true`, running `ai-container` from inside (or below) any of a workspace's `dirs` loads that workspace automatically, no flag needed. The active workspace's name is printed on startup on the same line as the container name (`podman container: ai-x7q (Workspace: frontend)`); it is omitted when no workspace is active.

### Vertex AI

Export three variables on the host, then launch either assistant:

```bash
gcloud auth application-default login
export GCLOUD_PROJECT="your-project-id"
export VERTEX_LOCATION="global"
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/gcloud/application_default_credentials.json"
ai-container --claude      # or --opencode
```

The launcher derives each tool's own variable names:

| Purpose | Claude Code | OpenCode |
|---|---|---|
| Select Vertex | `CLAUDE_CODE_USE_VERTEX=1` (set when `VERTEX_LOCATION` is non-empty) | pick a Vertex model with `/models` |
| Project | `ANTHROPIC_VERTEX_PROJECT_ID` (from `GCLOUD_PROJECT`) | `GOOGLE_CLOUD_PROJECT` (from `GCLOUD_PROJECT`) |
| Location | `CLOUD_ML_REGION` (from `VERTEX_LOCATION`; Claude defaults to `us-east5` without it) | `VERTEX_LOCATION` |
| Credentials | `GOOGLE_APPLICATION_CREDENTIALS` | `GOOGLE_APPLICATION_CREDENTIALS` |

The file named by the host `GOOGLE_APPLICATION_CREDENTIALS` is mounted read-only at `/home/coder/.config/gcloud/application_default_credentials.json` and the in-container variable points there. Project entries are skipped when `GCLOUD_PROJECT` is unset or empty, the credentials entries when the file doesn't exist. Nothing is printed or passed in environment variables from the file's contents. The project needs the Vertex AI API enabled, `roles/aiplatform.user`, and access to the models in a location that supports them. Other ADC sources (e.g. an attached service account) can work without a credentials file. To use different projects or locations per tool, override an entry in `extra_envs`/`--extra-env` (e.g. `CLOUD_ML_REGION=us-east5`) or drop one with `disable_envs`/`--disable-env`; disabling the credentials mount via `disable_mounts` also drops its variable.

### Custom /etc/hosts entries

Add static `/etc/hosts` entries inside the container, podman and docker (Apple's `container` tool has no equivalent flag):

```bash
ai-container --add-host openqa-ai.qam.suse.cz:169.254.1.2
```

Repeatable for multiple entries. See [Configuration file](#configuration-file) below for setting these as a standing per-host default instead.

### Custom entrypoint

You can specify a custom entrypoint using the `--entrypoint` flag:

```bash
# Run bash instead of the default entrypoint
ai-container --entrypoint /bin/bash

# Run a command with arguments (note the --)
ai-container --entrypoint /bin/echo -- hello world

# Pass arguments to the default entrypoint
ai-container -- --help
```

`--claude` and `--opencode` are shortcuts for the two bundled assistants' entrypoints; an explicit `--entrypoint` always takes precedence over either. Passing `--claude` and `--opencode` together is an error.

## Configuration file

For per-host defaults that shouldn't need to be typed on every invocation (e.g. a service only reachable from one particular machine), drop a `~/.config/ai-container.toml` (or set `$AI_CONTAINER_CONFIG` to point elsewhere). A fully commented template lives in [`ai-container.toml.example`](ai-container.toml.example):

```toml
add_hosts = ["openqa-ai.qam.suse.cz:169.254.1.2"]
extra_envs = ["MY_VARIABLE", "FIXED=value", "DERIVED=${MY_VARIABLE}"]
disable_envs = ["PUSHOVER_TOKEN"]
extra_mounts = ["~/.claude", "~/.config/gh:ro", "~/src/shared"]
disable_mounts = ["~/.aws", "~/.kube"]
ssh_agent = true
auto_workspaces = true
web_port = 4996
web_username = "coder"
web_password = "change-me"

[[workspace]]
name = "frontend"
dirs = ["/home/user/repos/app", "/home/user/repos/shared"]

[[workspace]]
name = "backend"
dirs = ["/home/user/repos/api"]
```

`add_hosts` entries combine additively with any `--add-host` flags on the command line, de-duplicated. On the `container` engine, config-supplied `add_hosts` are silently skipped (no `/etc/hosts` equivalent exists); an explicit `--add-host` on that engine is a hard error instead.

`extra_envs` lists the container's environment on top of the built-in [Vertex AI](#vertex-ai) variables; nothing else is set by default. `NAME` forwards the host value when set; `NAME=value` sets a literal, with `${HOST_VAR}` expanded from the host environment (no shell evaluation; the entry is skipped if a referenced variable is unset or empty). Entries combine with repeatable `--extra-env` flags; a flag entry with the same `NAME` replaces the config one. `env` was renamed to `extra_envs`; the old key is an error.

`disable_envs` (or `--disable-env NAME`) drops the named variables, built-in Vertex ones included; `--extra-env` flags always win. A config entry with the same `NAME` replaces a built-in one. Launcher-set variables (`HOME`, `SSH_AUTH_SOCK`, web-mode credentials) are not affected.

`extra_mounts` lists host directories or files to bind-mount as `SOURCE[:TARGET][:ro|rw]`, merged with `--extra-mount` and the built-in assistant mounts (config entries win on a target clash); `~` is expanded, relative sources resolve from the launch directory. Without `TARGET`, paths under `$HOME` map to the same path under `/home/coder`. See [`ai-container.toml.example`](ai-container.toml.example) for samples.

`disable_mounts` (or `--disable-mount PATH`, repeatable) takes absolute host paths (`~` is expanded, `..` is rejected). Any config `extra_mounts` entry, and the built-in assistant, Vertex credentials and `known_hosts` mounts, whose host path equals or sits below an entry is skipped, so `~/.config` drops every mount under it. Matching is lexical (no symlink resolution). `--extra-mount` flags, workspace dirs, the worktree parent and the working directory are never filtered.

`ssh_agent` (default `true`) controls SSH agent forwarding; `--ssh-agent` / `--no-ssh-agent` override it either way.

`[[workspace]]` entries each define a `name` and a list of `dirs` to mount together; see [Workspaces](#workspaces) above. `auto_workspaces` (default `false`) controls whether being inside one of those `dirs` loads its workspace without an explicit `--workspace` flag.

`web_port`, `web_username` and `web_password` set the [web mode](#web-mode) defaults (flags win). The password is stored in plaintext (`chmod 600` the file) and masked as `*****` at startup when it comes from here.

## What the launcher does

`ai-container` is a Python CLI (source under [`src/ai_container/`](src/ai_container/)) that assembles a single `podman run` / `docker run` / `container run` invocation: it never talks to a daemon API directly (the only probe is `docker info`, to detect rootless mode), so engine debug output (via `--debug-podman`, separate from the launcher's own `--debug`) reflects exactly what would happen if you ran the printed command yourself.

## Network Configuration

The container runs with `--network=pasta` instead of `slirp4netns`. Unlike `slirp4netns`, `pasta` shares the host's network stack more directly, so services bound to the host's loopback or wildcard address become reachable from inside the container. That's convenient for MCP servers running on the host that the container's AI assistants need to call, but it also means those services are no longer isolated behind the old slirp NAT boundary.

To keep that reachability without opening host services to the public zone, MCP servers are bound to a dedicated `dummy0` interface instead of loopback:

```bash
sudo nmcli connection add type dummy con-name dummy0 ifname dummy0 ip4 172.29.0.1/24
sudo firewall-cmd --permanent --zone=trusted --add-interface=dummy0
sudo firewall-cmd --permanent --new-policy=block-pub-dummy
sudo firewall-cmd --permanent --policy=block-pub-dummy --add-ingress-zone=public
sudo firewall-cmd --permanent --policy=block-pub-dummy --add-egress-zone=trusted
sudo firewall-cmd --permanent --policy=block-pub-dummy --set-target=REJECT
sudo firewall-cmd --reload
```

`dummy0` (`172.29.0.1/24`) sits in the `trusted` zone. The `block-pub-dummy` policy rejects any traffic from the `public` zone into `trusted`, so the `dummy0` interface stays reachable from the container (via pasta) but not from the network. Bind MCP servers to `172.29.0.1:<port>` on the host and point the container's MCP client config at that address.

This `pasta`/`dummy0` setup is podman/Linux-specific and doesn't apply when running with Docker or Apple's `container` tool. With Docker, containers use the default bridge network; reach host services via `host.docker.internal` on Docker Desktop, or `--add-host host.docker.internal:host-gateway` on Linux Engine.

On Apple's `container` tool, use its own domain-based mechanism instead (see [Host integration](https://github.com/apple/container/blob/main/docs/host-integration.md) in the `container` docs):

```bash
sudo container system dns create host.container.internal --localhost <ipv4-address>
```

Bind your MCP server to `127.0.0.1` on the host, then point the container's MCP client config at `host.container.internal:<port>`.

## Included Tools

- **Git ecosystem**: git, git-lfs, git-filter-repo, gh, glab, gitea-tea
- **Python**: python3, uv, ruff, flake8, yamllint
- **Perl**: perl, perltidy
- **Linters**: shellcheck, markdownlint-cli
- **Node.js**: npm, npx
- **Security**: gpg2, openssh-clients, gitleaks
- **Utilities**: bat, less, cnf, command-not-found
- **OBS/OSC**: osc, obs-service-*, osc-plugin-qam
- **AI Coding Assistants**: Claude Code, OpenCode

## Agent Skills

The image bakes the [`openqa` skill](https://github.com/plusky/openQA-skill) in for OpenCode
at build time (`~/.agents/skills/openqa`), since that path isn't mounted from the host and
only exists in the image layer — see the `Containerfile`.

Claude Code's skills directory (`~/.claude/skills/`) *is* mounted from the host (see
[What the launcher does](#what-the-launcher-does)), so baking a copy into the image would be
silently shadowed by that mount. Install it once instead, from inside any `ai-container`
session — the write lands on the host through the mount and persists across every future
run without touching the `Containerfile`:

```bash
npx --yes skills add plusky/openQA-skill --skill openqa -g -a claude-code -y --copy
```

Re-run either step later to pick up upstream `openqa` changes: rebuild the image for
OpenCode's copy, re-run the command above for Claude Code's.

## Development

The launcher is a standard `uv` project; the [`Containerfile`](Containerfile) (which builds the guest image) is unaffected by any of this.

```bash
uv sync              # install dependencies + dev tools into .venv/
uv run ai-container --help
uv run ruff format .       # format
uv run ruff check .        # lint
uv run mypy                # type-check (strict)
uv run pytest               # test suite (pytest + coverage)
```

Git hooks for this repo are defined declaratively in [`.githooks.config`](.githooks.config) (pre-commit: `ruff`, `scripts/check_hardcoded_config.py`, `gitleaks`; pre-push: `mypy` + `pytest`), using Git ≥2.55's config-driven hooks (`hook.<name>.*`, see `git help hook`). Git only honors `hook.*` settings from *protected* configuration (system/global/command scopes, never local repo config), so the tracked config file does nothing until you opt in once per clone:

```bash
git config set --local include.path ../.githooks.config
```

See [`AGENTS.md`](AGENTS.md) for more on the project layout and conventions.
