# AI Container

Containerized AI Coding Assistants environment based on openSUSE Tumbleweed.
Supports Claude Code and OpenCode, launched through a small `uv`-managed Python
CLI that drives Podman, Docker, or Apple's `container` tool.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Build the container image](#build-the-container-image)
- [Install the launcher](#install-the-launcher)
- [Usage](#usage)
  - [Basic usage](#basic-usage)
  - [Initialize assistant state](#initialize-assistant-state)
    - [Server mode](#server-mode)
  - [List running containers](#list-running-containers)
  - [Multiple containers](#multiple-containers)
  - [Custom mounts](#custom-mounts)
  - [Workspaces](#workspaces)
  - [Vertex AI](#vertex-ai)
  - [AWS Bedrock](#aws-bedrock)
  - [Custom /etc/hosts entries](#custom-etchosts-entries)
  - [Custom network arguments](#custom-network-arguments)
  - [Terminal integration](#terminal-integration)
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

Alternatively, Docker (Engine, rootless Engine, or Docker Desktop) works with
no extra packages.

On macOS, you need [Podman](https://podman.io) (running via
`podman machine`),
[Docker Desktop](https://www.docker.com/products/docker-desktop/), or Apple's
native [`container`](https://github.com/apple/container) tool (Apple silicon,
macOS 26+). For `container`, install it and start its services once:

```bash
container system start
container builder start
```

The launcher itself is a Python CLI run through
[`uv`](https://docs.astral.sh/uv/). Install `uv` (see its
[installation docs](https://docs.astral.sh/uv/getting-started/installation/));
it manages its own Python interpreter, so no separate Python install is
required on the host.

## Build the container image

```bash
podman build --pull=always --build-arg CODER_UID="$(id -u)" \
  --build-arg CODER_GID="$(id -g)" -t ai -f Containerfile .
```

With Docker (the image tag `ai` is what the launcher runs):

```bash
docker build --pull --build-arg CODER_UID="$(id -u)" \
  --build-arg CODER_GID="$(id -g)" -t ai -f Containerfile .
```

For rootless Docker the build-args don't matter (see
[below](#what-the-launcher-does)). Or with Apple's `container` tool:

```bash
container build --pull --build-arg CODER_UID="$(id -u)" \
  --build-arg CODER_GID="$(id -g)" -t ai -f Containerfile .
```

The image creates a `coder` user with UID/GID `1000:1000` by default. Pass
`CODER_UID` and `CODER_GID` when your host UID/GID differ, or when running
through the Podman macOS VM. Rebuild the image if the host UID/GID you want to
use changes.

## Install the launcher

From a checkout of this repository:

```bash
uv tool install .
```

This puts an `ai-container` command on your `$PATH` (via `uv tool`'s shim
directory). Upgrade after pulling changes with `uv tool upgrade ai-container`,
or reinstall with `uv tool install --reinstall .`.

While developing the launcher itself, run it in place instead, without
installing:

```bash
uv run ai-container ...
```

## Usage

### Basic usage

```text
ai-container [WRAPPER OPTIONS] -- [TOOL ARGS]
```

Everything before `--` configures the launcher itself (engine, mounts, server
mode, ...). Everything after `--` is passed straight through to the entrypoint
running inside the container (OpenCode, Claude Code, Codex, Copilot, pi, or
whatever `--entrypoint` points at).

`--` is only *required* when the tool argument you're forwarding collides with
one of the launcher's own flag names (see the list in `ai-container --help`) or
with `-h`/`--help`. The CLI is built with Click/Typer's
`ignore_unknown_options`, so it keeps scanning the whole command line for
flags it recognizes rather than stopping at the first one it doesn't — any
other option-looking token (`-c`, `--resume`, ...) is forwarded to the
entrypoint automatically, no `--` needed:

```bash
ai-container
# initialize persistent skills and configuration
ai-container init
ai-container --claude
ai-container --codex
ai-container --copilot
ai-container --pi
# assistant names also work as subcommands
ai-container pi -p 'summarize this repo'
# --resume isn't ours, forwarded automatically
ai-container --claude --resume
ai-container --entrypoint /bin/bash -c 'echo hi'   # same for -c
# --debug *is* ours; -- forwards the literal flag instead
ai-container --claude -- --debug
# forward a host environment variable when set
ai-container --extra-env MY_VARIABLE
# set a variable, expanding host variables
ai-container --extra-env 'X=${HOME}/y'
```

Common modes are also available as subcommands, which are sugar for the matching
flag (the flag spellings keep working):

| Subcommand | Same as | Purpose |
| --- | --- | --- |
| `ai-container init` | `--init` | Initialize host-persisted assistant state. |
| `ai-container server` | `--server` | Run OpenCode as a detached HTTP server. |
| `ai-container attach` | `--attach` | Require an existing server for this directory. |
| `ai-container continue` | forwarding `--continue` | Resume the assistant's last session. |
| `ai-container list` | `--list` | List running containers. |
| `ai-container shell` | `--shell` | Open a bash shell, attaching to this directory's container if one runs. |
| `ai-container help` | `-h`/`--help` | Show the launcher help. |

Because subcommands are read from the first positional token, a literal
`init`, `server`, `attach`, `continue`, `list`, `shell`, or `help` cannot be
forwarded to the entrypoint. Use `--entrypoint opencode help` when you need
OpenCode's own help.

This is a deliberate (and arguably improved) departure from the old bash
script's parsing, which stopped recognizing its own flags entirely as soon as
it saw the first argument it didn't understand. Since `ai-container` keeps
recognizing its own flags anywhere on the command line, only genuine name
collisions need `--`.

Run `ai-container --help` for the full, coloured option reference.

The launcher automatically:

- Picks a container runtime: `podman` by default, then Apple's `container` on
  macOS, then `docker`. Override with `--runtime podman|container|docker` or the
  `AI_CONTAINER_RUNTIME` environment variable.
- Optionally runs the container inside a KVM microVM instead of plain
  namespaces, via crun's `krun` OCI runtime. Enable with `--microvm` (podman
  only; needs the `crun-krun` package and `/dev/kvm` access).
- Mounts the current directory at the same absolute path inside the container,
  so `pwd` matches on both sides. If it's under your host `$HOME`, it's remapped
  onto `/home/coder` instead (e.g. host `~/external/ai-container` → container
  `/home/coder/external/ai-container`), so `~`-relative paths line up too.
  Refuses to run if the current directory is your entire `$HOME`.
- Detects if the current directory is a git worktree and automatically
  rw-mounts the parent checkout (the repo containing the real `.git` directory)
  at the equivalent container path. Disable with `--no-worktree-mount`.
- Uses `/home/coder` as the container home.
- Runs as the image's `coder` user (podman: via `--userns=keep-id`;
  `container` and rootful docker: via `--uid`/`--gid` or `--user` matching the
  host user; rootless docker, detected with `docker info`: as container uid 0,
  which the daemon maps to your unprivileged host user so bind mounts stay
  writable).
- Configures SELinux labels when needed (podman/Linux: `:z`/`:Z` mount labels;
  docker: `--security-opt label=disable`, so host files are never relabeled).
- Forwards SSH agent for git operations unless disabled with `--no-ssh-agent` /
  `ssh_agent = false` (podman and docker: Linux only, by mounting the socket;
  Docker Desktop on macOS: via its `/run/host-services/ssh-auth.sock` relay;
  `container`: via its built-in `--ssh` forwarding, macOS only).
- Mounts `~/.ssh/known_hosts` read-only, and read-write `~/.agents`,
  `~/.claude`, `~/.claude.json`, `~/.config/opencode`,
  `~/.local/share/opencode`, `~/.local/state/opencode`, `~/.cache/opencode`
  and `~/.pi/agent` (all skippable with `--disable-mount` / `disable_mounts`).
- Sets up [Vertex AI](#vertex-ai) from three host variables.
- Forwards the provider keys `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY` and `OPENROUTER_API_KEY` by name when set on the host
  (disable with `--disable-env`).
- Mounts and forwards nothing else by default: other credentials, tool
  configs, caches and environment variables come from the
  [configuration file](#configuration-file) (`extra_mounts`, `extra_envs`).
  Mounts only happen if the host path exists (a `✗ ... not found` line is
  printed with `--debug` otherwise); the container runs with `--rm`, so create
  directories such as `~/.local/share/opencode` on the host first if you want
  data like OpenCode session history to persist.
- Assigns a random container name (e.g. `ai-x7q`) printed on every run.

> [!NOTE]
> `--microvm` is new and only lightly tested: it adds `--annotation
> krun.use_passt=1` so pasta networking (see
> [Network Configuration](#network-configuration)) routes into the guest
> microVM, but this hasn't been verified on real hardware. If host-bound
> services aren't reachable from inside a `--microvm` container, that
> annotation is the first thing to check.
>
> GPG agent forwarding isn't supported: Apple's `container` tool can't
> bind-mount a host AF_UNIX socket file into its VM (the socket node isn't
> accessible through its virtiofs share), so signing commits with a forwarded
> host agent doesn't work from inside the container on either runtime.
>
> `container`'s `--ssh` forwarding always creates its relay socket owned by
> `root` inside the guest, regardless of `container` version
> ([apple/container#580](https://github.com/apple/container/issues/580) only
> made the guest copy inherit the host socket's exact mode bits, not its
> ownership). Since we run as the non-root `coder` user (see above), the
> launcher works around this by backgrounding a `chmod 0666` on that
> per-container relay socket (via `container exec -u root`, retried for up to
> 2s while the container boots). This only loosens the ephemeral, per-container
> copy of the socket living in that container's own private VM, not your real
> host `ssh-agent` socket.

### Initialize assistant state

Run initialization once after building the image, and again whenever you want
to update the installed skills and generated assistant configuration:

```bash
ai-container init
```

The command creates any missing built-in assistant mount paths on the host,
leaving every existing path untouched, then runs [`init.sh`](init.sh) inside
the container. Its changes persist through the default mounts. Initialization
installs the OpenQA, openSUSE packaging, and frontend design skills, Caveman, the RTK and Graphify
assistant configuration, and SkillSpector's `/skillspector` command and
`skillspector_scan` tool for OpenCode.

`--init` can't be combined with an assistant shortcut, `--entrypoint`, `--shell`
or `--server`.

### Server mode

OpenCode starts a network server by default, including when you use the TUI.
The server binds to `0.0.0.0` inside the container and is published on all host
interfaces. The container port is `4996`, and the launcher publishes it on host
port `4996` too, so inside and outside match. If `4996` is occupied, it walks up
to `5499`. The launcher prints one status line when it starts or attaches:

```text
* Starting server + TUI - opencode:PASSWORD@192.168.1.2:4996
* Attaching to server - 192.168.1.2:4996
* Starting server - opencode:PASSWORD@192.168.1.2:4996
```

The line lists the host addresses other machines can reach, comma separated;
loopback and link-local addresses are omitted, and `localhost` appears only when
no other address was found. Credentials are only printed when a new server
starts; an attach reuses the existing container's password. Port probing is not
a reservation: simultaneous starts can still race. Retry the launch if the
engine reports that a port became occupied.

On podman/docker, another launch from the same directory attaches to its
existing server. Only containers with the OpenCode server label are reused;
a shell or another assistant's container is not a server. Reuse keeps the
existing container's mounts, environment, and credentials. Use `--no-attach`
to apply changed launch settings in a fresh container.

```bash
ai-container                    # start a server and TUI, or attach to this directory's server
ai-container attach             # require an existing server; fail if none exists
ai-container --no-attach        # fresh server and TUI on an available port
```

A foreground container ends when its initial TUI exits. Clients attached to
that server then disconnect. For a server that survives TUI exit, use:

```bash
ai-container server
```

The container runs detached. Repeating `--server` reuses an existing server for
the directory. Closing an attached TUI does not stop a detached server. Server
mode supports OpenCode (HTTP) and pi (`--server --pi`, JSONL RPC over TCP).
Stop and remove a detached container with `podman rm -f CONTAINER` (or
`docker rm -f CONTAINER`), using the name printed on startup.

OpenCode V2 fixes the HTTP basic auth username to `opencode`; other values fail.
The default password comes from the host's `~/.config/opencode/service.json`,
or is generated for the new container when absent. `--password` overrides it.
Auto-attach inherits the existing container's password; an explicit password
override must match that server. `ai-container init` configures the shared
service hostname to `0.0.0.0`; the launcher also passes the bind address
explicitly.

Check from the host, or another container that can reach the host IP:

```bash
# Substitute the URL and password printed on startup.
read -rs OPENCODE_PASSWORD; export OPENCODE_PASSWORD; echo
opencode --server http://HOST_IP:PORT api get /api/info
opencode --server http://HOST_IP:PORT
```

An authenticated `/api/info` response confirms access to that server.
In another container, `127.0.0.1` refers to that container, not the server's host.
Only the server container's mounted files are available to remote clients.
Protect the published ports with your firewall. HTTP basic auth is not encrypted;
use a trusted network, SSH tunnel, or TLS proxy for remote access.

Native OpenCode administrative commands, explicit `--server URL`, and
`--standalone` bypass managed startup. Forward colliding native flags after `--`.
Apple `container` starts new servers but does not support automatic reuse here.

Additional server options:

| Flag | Default | Description |
| --- | --- | --- |
| `--server-port PORT` | `4996`, then next free | Published host port; container port stays `4996` |
| `--server-username USER` | `opencode` | HTTP basic auth username (only `opencode` is supported) |
| `--password PASS`, `--server-password PASS` | *(service config, otherwise random)* | HTTP basic auth password |
| `--attach` | *(automatic reuse)* | Require a server for this directory |
| `--no-attach` | *(off)* | Skip reuse; start a fresh network server |

#### pi RPC server

`--server --pi` publishes pi's JSONL RPC protocol on TCP port `4996` (or
`--server-port`). socat starts one `pi --mode rpc` process per connection. There
is no password and no TLS; firewall the port or tunnel it over SSH. This is a
stdio-to-TCP bridge, not an HTTP server, so `--attach` and
`--server-password` do not apply.

```bash
ai-container --server --pi --model openai/gpt-5
# then, from another machine:
socat - TCP:HOST_IP:4996
```

Send JSONL commands such as `{"id":"1","type":"get_state"}` and read the
matching responses and events. Upstream pi RPC is stdio-only; without the
launcher's socat bridge it only works in a foreground process.

### List running containers

`ai-container list` (also `--list`) prints one line per running container
started by the launcher:

```text
ai-x7q - /home/coder/project - /usr/local/bin/opencode-launch --continue - 4996 - ****
```

Fields are container name, workdir, executed command (entrypoint plus args),
published host port, and server password. Unknown values are shown as `-`.
Passwords are masked; add `--show-secrets` to print the real value. The list is
sorted by workdir. Apple's `container` engine has no label filter, so `list`
reports that it is unsupported there.

### Multiple containers

OpenCode V2 records its native background service (URL and pid) in
`$XDG_STATE_HOME/opencode/service.json`. The launcher sets `XDG_STATE_HOME` to a
private, per-container directory, so every container registers its own service
instead of overwriting the host's or another container's. Native service discovery
therefore remains isolated between containers.

Launcher-managed servers use explicit authenticated connections instead of
native service discovery, so `opencode service status` does not describe them.
Use `opencode --server URL api get /api/info` to check a published server.

The shared `~/.config/opencode/service.json` still applies to all of them. If
service mode was previously disabled there with `opencode service set disabled
true`, re-enable it once:

```bash
opencode service unset disabled
```

### Custom mounts

Bind-mount additional host directories or files into the container, in
addition to the current directory and any auto-detected git worktree parent.
The format is `SOURCE[:TARGET][:ro|rw]` (read-write by default):

```bash
ai-container --extra-mount ~/repos/b
```

`-m` is a shorthand for `--extra-mount`. Repeatable:

```bash
ai-container -m ~/repos/b -m ~/repos/shared-libs:ro -m ~/notes:/opt/notes:ro
```

Without `TARGET`, paths follow the same `$HOME`-remap rule as the workdir
mount; `TARGET` must be absolute. On a target clash the first mount wins
(workdir, then CLI, config, workspace dirs, worktree parent, built-in defaults,
`known_hosts`), so a clashing mount is skipped automatically.

The old `--mount-extra` and `--env` spellings no longer exist; because unknown
options are forwarded, they now reach the assistant as ordinary arguments.

### Workspaces

Named groups of directories, defined in the
[configuration file](#configuration-file), that get mounted together in one
shot instead of listing them all with repeated `--extra-mount` flags:

```bash
ai-container --workspace frontend
```

`--workspace` always looks the name up in the config file's `[[workspace]]`
entries, regardless of `auto_workspaces`, and errors out if it isn't defined.
With `auto_workspaces = true`, running `ai-container` from inside (or below)
any of a workspace's `dirs` loads that workspace automatically, no flag needed.
The active workspace's name is printed on startup on the same line as the
container name (`podman container: ai-x7q (Workspace: frontend)`); it is
omitted when no workspace is active.

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

- Select Vertex
  - Claude Code: `CLAUDE_CODE_USE_VERTEX=1`, set when `VERTEX_LOCATION` is
    non-empty
  - OpenCode: pick a Vertex model with `/models`
- Project
  - Claude Code: `ANTHROPIC_VERTEX_PROJECT_ID` from `GCLOUD_PROJECT`
  - OpenCode: `GOOGLE_CLOUD_PROJECT` from `GCLOUD_PROJECT`
- Location
  - Claude Code: `CLOUD_ML_REGION` from `VERTEX_LOCATION`; Claude defaults to
    `us-east5` without it
  - OpenCode: `VERTEX_LOCATION`
- Credentials
  - Claude Code: `GOOGLE_APPLICATION_CREDENTIALS`
  - OpenCode: `GOOGLE_APPLICATION_CREDENTIALS`

The file named by the host `GOOGLE_APPLICATION_CREDENTIALS` is mounted
read-only at
`/home/coder/.config/gcloud/application_default_credentials.json` and the
in-container variable points there. Project entries are skipped when
`GCLOUD_PROJECT` is unset or empty, the credentials entries when the file
doesn't exist. Nothing is printed or passed in environment variables from the
file's contents. The project needs the Vertex AI API enabled,
`roles/aiplatform.user`, and access to the models in a location that supports
them. Other ADC sources (e.g. an attached service account) can work without a
credentials file. To use different projects or locations per tool, override
an entry in `extra_envs`/`--extra-env` (e.g.
`CLOUD_ML_REGION=us-east5`) or drop one with
`disable_envs`/`--disable-env`; disabling the credentials mount via
`disable_mounts` also drops its variable.

### AWS Bedrock

OpenCode talks to Bedrock directly; the launcher only has to make the profile
visible. `~/.aws` is not mounted by default:

```bash
ai-container --extra-mount ~/.aws --opencode
```

```jsonc
// ~/.config/opencode/opencode.jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "providers": {
    "amazon-bedrock": { "settings": { "profile": "bedrock", "region": "eu-central-1" } }
  }
}
```

Keep the mount read-write: SSO profiles, MFA role caches and
`credential_process` rewrite files under `~/.aws` (static keys in
`~/.aws/credentials` work with `:ro`). Run `aws sso login --profile PROFILE` on
the host when the session expires — that step needs a browser; the container
reuses the refreshed cache through the mount. The profile needs
`bedrock:ListFoundationModels` plus model invocation permissions. For a
permanent setup, add `extra_mounts = ["~/.aws"]` to the
[configuration file](#configuration-file).

### Custom /etc/hosts entries

Add static `/etc/hosts` entries inside the container, podman and docker
(Apple's `container` tool has no equivalent flag):

```bash
ai-container --add-host openqa-ai.qam.suse.cz:169.254.1.2
```

Repeatable for multiple entries. See
[Configuration file](#configuration-file) below for setting these as a
standing per-host default instead.

### Custom network arguments

Pass raw extra network arguments to the engine, one token per
`--network-arg` (repeatable). On podman, a `--network=...` (or `--net=...`)
value replaces the default `--network=pasta`; `--userns=keep-id` is kept. To
attach the container to the host's `dummy0` interface with its own address,
gateway and DNS server (see [Network Configuration](#network-configuration)):

```bash
ai-container \
  --network-arg=--network=pasta:-i,dummy0,-a,172.29.0.2,-n,24,-g,172.29.0.1 \
  --network-arg=--dns=1.1.1.1
```

In the pasta options, `-i` is the host interface, `-a` the container's address,
`-n` its prefix length and `-g` its gateway; `--dns` sets the resolver. Use
`--dns=172.29.0.1` instead only if the host runs a resolver on that address. Use
the `--network-arg=VALUE` form, since the value starts with `--`. Other
arguments are appended after the defaults. The values aren't validated or
restricted per engine. The container reaches host services on `172.29.0.1` and
the internet through the gateway. To set them as a standing default, use
`extra_network_args` in the [configuration file](#configuration-file):

```toml
extra_network_args = [
  "--network=pasta:-i,dummy0,-a,172.29.0.2,-n,24,-g,172.29.0.1",
  "--dns=1.1.1.1",
]
```

### Shell

`ai-container shell` (or `--shell`) opens a bash shell. If a container started
from the current directory is already running (podman/docker), it `exec`s into
the newest one; otherwise it starts a new container running `/bin/bash`. Extra
args go to bash. Containers started before this flag existed carry no label and
aren't found; Apple `container` always starts a new one. Can't be combined with
an assistant shortcut, `--entrypoint` or `--server`.

### Terminal integration

Interactive sessions inherit `TERM` and `COLORTERM` and use the host's system
terminfo database when available. The launcher temporarily sets the terminal
title and restores it on exit. It also clears mouse reporting, bracketed paste,
the alternate screen and other modes that a crashed TUI could leave enabled.

Mouse reporting itself remains application-controlled.

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

`--claude`, `--opencode`, `--codex`, `--copilot` and `--pi` are shortcuts for
the bundled assistants' entrypoints; an explicit `--entrypoint` always takes
precedence over a shortcut, and assistant shortcuts are mutually exclusive.
`ai-container pi`, `opencode`, `claude`, `codex` and `copilot` are equivalent
subcommands. A forwarded token after `--` stays literal, so `ai-container --
pi` sends the word `pi` to the default entrypoint instead of launching pi.

## Configuration file

For per-host defaults that shouldn't need to be typed on every invocation
(e.g. a service only reachable from one particular machine), drop a
`~/.config/ai-container.toml` (or set `$AI_CONTAINER_CONFIG` to point
elsewhere). A fully commented template lives in
[`ai-container.toml.example`](ai-container.toml.example):

```toml
default_agent = "pi"
add_hosts = ["openqa-ai.qam.suse.cz:169.254.1.2"]
extra_network_args = ["--network=pasta:-i,dummy0,-a,172.29.0.2,-n,24,-g,172.29.0.1", "--dns=1.1.1.1"]
extra_envs = ["MY_VARIABLE", "FIXED=value", "DERIVED=${MY_VARIABLE}"]
disable_envs = ["PUSHOVER_TOKEN"]
extra_mounts = ["~/.claude", "~/.config/gh:ro", "~/src/shared"]
disable_mounts = ["~/.aws", "~/.kube"]
ssh_agent = true
auto_workspaces = true

[[workspace]]
name = "frontend"
dirs = ["/home/user/repos/app", "/home/user/repos/shared"]

[[workspace]]
name = "backend"
dirs = ["/home/user/repos/api"]
```

`default_agent` selects the assistant launched when no assistant shortcut,
subcommand or `--entrypoint` is given. Valid values are `opencode`, `claude`,
`codex`, `copilot` and `pi`; the default is `opencode`. Explicit CLI selection
always wins. `--server` accepts `opencode` (HTTP) and `pi` (TCP RPC).

`add_hosts` entries combine additively with any `--add-host` flags on the
command line, de-duplicated. On the `container` engine, config-supplied
`add_hosts` are silently skipped (no `/etc/hosts` equivalent exists); an
explicit `--add-host` on that engine is a hard error instead.

`extra_network_args` lists raw engine network arguments, combined additively
with `--network-arg` flags and de-duplicated (see
[Custom network arguments](#custom-network-arguments)). A `--network=...` entry
replaces the default `--network=pasta` on podman.

`extra_envs` lists the container's environment on top of the built-in
[Vertex AI](#vertex-ai) variables and the provider keys
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` and
`OPENROUTER_API_KEY`. Those four are forwarded by name (value-less `-e NAME`,
so the secret stays out of the process list) when set on the host, unless
disabled. `NAME` forwards the host value when set; `NAME=value` sets a literal, with
`${HOST_VAR}` expanded from the host environment (no shell evaluation; the
entry is skipped if a referenced variable is unset or empty). Entries combine
with repeatable `--extra-env` flags; a flag entry with the same `NAME` replaces
the config one. `env` was renamed to `extra_envs`; the old key is an error.

`export_vars` maps a variable name to a host command whose stdout becomes its
value, e.g. `export_vars = { GH_TOKEN = "gh auth token" }` (useful when a token
lives in the host keyring). The command runs at launch without a shell (no
pipes or `&&`) and the variable is skipped if it fails or prints nothing. It
overrides `extra_envs`; `--extra-env` and `disable_envs` win over it.

`disable_envs` (or `--disable-env NAME`) drops the named variables, built-in
Vertex ones included; `--extra-env` flags always win. A config entry with the
same `NAME` replaces a built-in one. Launcher-set variables (`HOME`,
`SSH_AUTH_SOCK`, server-mode credentials) are not affected.

`extra_mounts` lists host directories or files to bind-mount as
`SOURCE[:TARGET][:ro|rw]`, merged with `--extra-mount` and the built-in
assistant mounts (config entries win on a target clash); `~` is expanded,
relative sources resolve from the launch directory. Without `TARGET`, paths
under `$HOME` map to the same path under `/home/coder`. See
[`ai-container.toml.example`](ai-container.toml.example) for samples.

`disable_mounts` (or `--disable-mount PATH`, repeatable) takes absolute host
paths (`~` is expanded, `..` is rejected). Any config `extra_mounts` entry,
and the built-in assistant, Vertex credentials and `known_hosts` mounts, whose
host path equals or sits below an entry is skipped, so `~/.config` drops every
mount under it. Matching is lexical (no symlink resolution). `--extra-mount`
flags, workspace dirs, the worktree parent and the working directory are never
filtered.

`ssh_agent` (default `true`) controls SSH agent forwarding; `--ssh-agent` /
`--no-ssh-agent` override it either way.

`[[workspace]]` entries each define a `name` and a list of `dirs` to mount
together; see [Workspaces](#workspaces) above. `auto_workspaces` (default
`false`) controls whether being inside one of those `dirs` loads its workspace
without an explicit `--workspace` flag.

## What the launcher does

`ai-container` is a Python CLI (source under
[`src/ai_container/`](src/ai_container/)) that assembles an engine `run` or `exec`
invocation. It probes containers and published ports through engine CLI commands;
it never talks to a daemon API directly. `--debug-runtime` prints the runtime
command with OpenCode passwords redacted. `--debug` controls launcher/OpenCode
logging separately.

## Network Configuration

The container runs with `--network=pasta` instead of `slirp4netns`. Unlike
`slirp4netns`, `pasta` shares the host's network stack more directly, so
services bound to the host's loopback or wildcard address become reachable
from inside the container. That's convenient for MCP servers running on the
host that the container's AI assistants need to call, but it also means those
services are no longer isolated behind the old slirp NAT boundary.

To keep that reachability without opening host services to the public zone,
MCP servers are bound to a dedicated `dummy0` interface instead of loopback:

```bash
sudo nmcli connection add type dummy con-name dummy0 ifname dummy0 ip4 172.29.0.1/24
sudo firewall-cmd --permanent --zone=trusted --add-interface=dummy0
sudo firewall-cmd --permanent --new-policy=block-pub-dummy
sudo firewall-cmd --permanent --policy=block-pub-dummy --add-ingress-zone=public
sudo firewall-cmd --permanent --policy=block-pub-dummy --add-egress-zone=trusted
sudo firewall-cmd --permanent --policy=block-pub-dummy --set-target=REJECT
sudo firewall-cmd --reload
```

`dummy0` (`172.29.0.1/24`) sits in the `trusted` zone. The `block-pub-dummy`
policy rejects any traffic from the `public` zone into `trusted`, so the
`dummy0` interface stays reachable from the container (via pasta) but not from
the network. Bind MCP servers to `172.29.0.1:<port>` on the host and point the
container's MCP client config at that address.

To attach the container to `dummy0` itself with its own address (`172.29.0.2`),
gateway (`172.29.0.1`, the host) and DNS server, pass
`--network-arg=--network=pasta:-i,dummy0,-a,172.29.0.2,-n,24,-g,172.29.0.1` and
`--network-arg=--dns=1.1.1.1`, or the equivalent `extra_network_args` (see
[Custom network arguments](#custom-network-arguments)). Without `-a`/`-g`,
pasta copies the host's own `dummy0` address into the container and, since
`dummy0` has no gateway, the container has no routes. `--dns=172.29.0.1` only
works if the host runs a resolver on that address.

Alternatively, give the container's network a dedicated firewalld zone that
accepts everything, instead of `trusted`:

```bash
sudo firewall-cmd --permanent --new-zone=ai-container
sudo firewall-cmd --permanent --zone=ai-container --set-target=ACCEPT
sudo firewall-cmd --permanent --zone=trusted --remove-interface=dummy0
sudo firewall-cmd --permanent --policy=block-pub-dummy --remove-egress-zone=trusted
sudo firewall-cmd --permanent --policy=block-pub-dummy --add-egress-zone=ai-container
sudo firewall-cmd --reload
sudo nmcli connection modify dummy0 connection.zone ai-container
sudo nmcli connection up dummy0
```

The zone must exist (after the reload) before NetworkManager can assign
`dummy0` to it. The `block-pub-dummy` policy now targets the new zone, so the
`public` zone still can't reach `dummy0`. Untested: pasta connects from the
host's own sockets, so firewalld may not filter container-to-host traffic at
all.

This `pasta`/`dummy0` setup is podman/Linux-specific and doesn't apply when
running with Docker or Apple's `container` tool. With Docker, containers use
the default bridge network; reach host services via `host.docker.internal` on
Docker Desktop, or `--add-host host.docker.internal:host-gateway` on Linux
Engine.

On Apple's `container` tool, use its own domain-based mechanism instead (see
[Host integration](https://github.com/apple/container/blob/main/docs/host-integration.md)
in the `container` docs):

```bash
sudo container system dns create host.container.internal --localhost <ipv4-address>
```

Bind your MCP server to `127.0.0.1` on the host, then point the container's MCP
client config at `host.container.internal:<port>`.

## Included Tools

- **Git ecosystem**: git, git-lfs, git-filter-repo, gh, glab, gitea-tea
- **Python**: python3, uv, ruff, flake8, yamllint
- **Perl**: perl, perltidy
- **Linters**: shellcheck, markdownlint-cli
- **Node.js**: npm, npx
- **Browser automation**: headless Chromium, Playwright MCP (`playwright-mcp`, disabled by default in the OpenCode config)
- **Security**: gpg2, openssh-clients, gitleaks, SkillSpector
- **Utilities**: bat, less, cnf, command-not-found
- **OBS/OSC**: osc, obs-service-*, osc-plugin-qam
- **AI Coding Assistants**: Claude Code, OpenCode, Codex, GitHub Copilot CLI, pi

## Agent Skills

`ai-container init` installs the bundled skills into the host-mounted
`~/.agents` directory. Re-run it to pick up upstream changes without rebuilding
the image.

## Development

The launcher is a standard `uv` project; the
[`Containerfile`](Containerfile) (which builds the guest image) is unaffected
by any of this.

```bash
uv sync              # install dependencies + dev tools into .venv/
uv run ai-container --help
uv run ruff format .       # format
uv run ruff check .        # lint
uv run mypy                # type-check (strict)
uv run pytest               # test suite (pytest + coverage)
```

Git hooks for this repo are defined declaratively in
[`.githooks.config`](.githooks.config) (pre-commit: `ruff`,
`scripts/check_hardcoded_config.py`, `gitleaks`; pre-push: `mypy` + `pytest`),
using Git ≥2.55's config-driven hooks (`hook.<name>.*`, see `git help hook`). Git
only honors `hook.*` settings from *protected* configuration
(system/global/command scopes, never local repo config), so the tracked config
file does nothing until you opt in once per clone:

```bash
git config set --local include.path ../.githooks.config
```

See [`AGENTS.md`](AGENTS.md) for more on the project layout and conventions.
