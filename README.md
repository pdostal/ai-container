# AI Container

Containerized AI Coding Assistants environment based on openSUSE Tumbleweed. Supports Claude Code and OpenCode.

## Prerequisities

```bash
sudo transactional-update pkg install crun libkrun1 libkrunfw5 slirp4netns
```

On macOS, you need either [Podman](https://podman.io) (running via `podman machine`) or Apple's native [`container`](https://github.com/apple/container) tool (Apple silicon, macOS 26+). For `container`, install it and start its services once:

```bash
container system start
container builder start
```

## Build

```bash
podman build --build-arg CODER_UID="$(id -u)" --build-arg CODER_GID="$(id -g)" -t ai -f Containerfile .
```

Or with Apple's `container` tool:

```bash
container build --build-arg CODER_UID="$(id -u)" --build-arg CODER_GID="$(id -g)" -t ai -f Containerfile .
```

The image creates a `coder` user with UID/GID `1000:1000` by default. Pass `CODER_UID` and `CODER_GID` when your host UID/GID differ, or when running through the Podman macOS VM. Rebuild the image if the host UID/GID you want to use changes.

## Run

```bash
./ai-container
```

The `ai-container` script automatically:
- Picks a container runtime: `podman` by default, falling back to Apple's `container` on macOS if `podman` isn't installed. Override with `--runtime podman|container` or the `AI_CONTAINER_RUNTIME` environment variable.
- Mounts the current directory at the same absolute path inside the container, so `pwd` matches on both sides. If it's under your host `$HOME`, it's remapped onto `/home/coder` instead (e.g. host `~/external/ai-container` → container `/home/coder/external/ai-container`), so `~`-relative paths line up too. Refuses to run if the current directory is your entire `$HOME`.
- Detects if the current directory is a git worktree and automatically rw-mounts the parent checkout (the repo containing the real `.git` directory) at the equivalent container path. Disable with `--no-worktree-mount`.
- Uses `/home/coder` as the container home
- Mounts configuration from the host home directory into `/home/coder`
- Runs as the image's `coder` user (podman: via `--userns=keep-id`; `container`: via `--uid`/`--gid` matching the host user, since its bind mounts show files owned by whichever uid/gid the process runs as)
- Configures SELinux labels when needed (podman/Linux only)
- Forwards SSH agent for git operations (podman: Linux only; `container`: via its built-in `--ssh` forwarding, macOS only)
- Mounts credentials read-only (GitHub CLI, Git config, SSH known_hosts, OSC config)
- Forwards `$BUGZILLA_API_KEY` from the host environment when set
- Mounts AI assistant configurations for persistence (Claude Code; OpenCode config, data, and state). These rw mounts only happen if the host directory already exists (a `✗ ... not found` line is printed otherwise); the container runs with `--rm`, so create the directory on the host first (e.g. `mkdir -p ~/.local/share/opencode`) if you want data such as OpenCode session history (needed for `opencode -s <session-id>`) to persist across runs.
- Optionally mounts Google Cloud credentials when available
- Assigns a random container name (e.g. `ai-x7q`) printed on every run

> [!NOTE]
> GPG agent forwarding isn't supported: Apple's `container` tool can't bind-mount a host AF_UNIX socket file into its VM (the socket node isn't accessible through its virtiofs share), so signing commits with a forwarded host agent doesn't work from inside the container on either runtime.

> [!NOTE]
> `container`'s `--ssh` forwarding always creates its relay socket owned by `root` inside the guest, regardless of `container` version ([apple/container#580](https://github.com/apple/container/issues/580) only made the guest copy inherit the host socket's exact mode bits, not its ownership). Since we run as the non-root `coder` user (see above), the script works around this by backgrounding a `chmod 0666` on that per-container relay socket (via `container exec -u root`, retried for up to 50s while the container boots). This only loosens the ephemeral, per-container copy of the socket living in that container's own private VM, not your real host `ssh-agent` socket.

### Web mode

Run OpenCode as a background web server:

```bash
./ai-container --web
```

The container runs detached. The web interface URL, username, and password are printed on startup.

Additional web options:

| Flag | Default | Description |
|---|---|---|
| `--web-port PORT` | `4996` | Port to expose the web interface on |
| `--web-username USER` | `coder` | HTTP basic auth username |
| `--web-password PASS` | *(random)* | HTTP basic auth password |

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

This `pasta`/`dummy0` setup is podman/Linux-specific and doesn't apply when running with Apple's `container` tool. To reach a host-bound MCP server from a container on `container`, use its own domain-based mechanism instead (see [Host integration](https://github.com/apple/container/blob/main/docs/host-integration.md) in the `container` docs):

```bash
sudo container system dns create host.container.internal --localhost <ipv4-address>
```

Bind your MCP server to `127.0.0.1` on the host, then point the container's MCP client config at `host.container.internal:<port>`.

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

## Custom Mounts

Mount additional host directories into the container read-write, in addition to the current directory and any auto-detected git worktree parent:

```bash
./ai-container --mount-extra ~/repos/b
```

Repeatable for multiple directories:

```bash
./ai-container --mount-extra ~/repos/b --mount-extra ~/repos/shared-libs
```

Extra paths follow the same `$HOME`-remap rule as the workdir mount, and duplicate mount targets (e.g. one already covered by the auto-detected worktree parent) are skipped automatically.

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
