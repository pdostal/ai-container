# Claude Code Container

Containerized AI Coding Assistants environment based on openSUSE Tumbleweed.

## Build

```bash
podman build -t ai -f Containerfile .
```

## Run

```bash
./ai-container
```

## Included Tools

- Git ecosystem: git, git-lfs, gh, glab, gitea-tea
- Python: python3, uv, ruff, flake8, yamllint
- Perl: perl, perltidy
- Linters: shellcheck, markdownlint-cli
- Node.js: npm, npx
- Security: gpg2, openssh-client
- Utilities: bat, less, cnf
- Claude Code CLI

