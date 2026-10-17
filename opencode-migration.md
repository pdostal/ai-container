# OpenCode 1 → OpenCode 2 migration

You are the coding agent operating in the **pdostal/ai-container** repository. **Implement the migration fully**, rather than producing a proposal. This file is the task specification and should stay committed as `opencode-migration.md`. Read `AGENTS.md`, `CLAUDE.md`, the repo source and tests, and the current upstream OpenCode V2 documentation before editing. Do not ask for routine confirmation. Keep existing user edits intact.

## References and version checks

Use the current **V2** docs (not V1 docs or stale V2 beta examples):

- https://dev.opencode.ai/v2/docs/
- https://dev.opencode.ai/v2/docs/migrate-v1/
- https://dev.opencode.ai/v2/docs/config/
- https://dev.opencode.ai/v2/docs/cli/config/
- https://dev.opencode.ai/v2/docs/cli/commands/
- https://dev.opencode.ai/v2/docs/cli/web/
- https://dev.opencode.ai/v2/docs/build/plugins/migrate-v1/
- https://dev.opencode.ai/v2/docs/plugins/

Verify commands and schema against the installed version's `--help` and/or official schemas. In the current V2 release, the npm package is `@opencode/cli` and the binary is named `opencode`, **not** `opencode2`. The server command is `opencode serve`.

## Required outcome

1. Install OpenCode **2** instead of OpenCode 1 in the container, without keeping duplicate V1 binaries.
2. Migrate **both types of OpenCode config**: all applicable global/project `opencode.json(c)` files to **native V2 server/project config** and the legacy global/project `tui.json(c)` files to **one global `~/.config/opencode/cli.json`**. Preserve the user's extensive existing settings and behavior wherever V2 supports them.
3. **Rename/convert all `*.jsonc` files in this repository to `*.json`**; convert all OpenCode-related `*.jsonc` files in the reachable global/mounted configuration locations too. Output must be **strict JSON**: remove JSONC comments and trailing commas without changing active values or string contents. **Delete all commented-out settings completely**, including disabled keys/blocks and commented examples embedded in migrated configuration files. Do not uncomment, migrate, activate, or archive these disabled settings in another file. Human explanatory comments about *active* settings may be moved to Markdown only when truly necessary; do not preserve commented-out settings as documentation. Rename references in source, scripts, tests, README, configs and documentation. No orphan `*.jsonc` files in the repository when done. Do not modify unrelated JSONC files elsewhere on the host or silently break tools that require a particular filename: investigate and report real exceptions rather than doing a blind `mv`.
4. Rename the launcher public interface `ai-container --web` to **`ai-container --server`**. Also rename `--web-port`, `--web-username` and `--web-password` to **`--server-port`, `--server-username` and `--server-password`**. Under the hood use `opencode serve`, not `opencode web`. Update code, conflicts, help text, docs, examples, tests and internal identifiers. Treat old wrapper flags as removed: don't accidentally pass them through to OpenCode as tool arguments.
5. Remove packages/files installed **only** as LSP servers because OpenCode 2 no longer runs those servers or its former LSP diagnostics, while retaining tools still required for compiling, testing, formatting, linting, or by Claude Code/Codex/Copilot/QA workflows.
6. Make skills, plugins, custom tools, agents, commands, MCP connections and persisted auth/session state work with V2 as far as available dependencies permit.

## Preserve safety and user data

- Inspect `git status` before changes. Do not overwrite existing edits, force-reset, or amend unrelated work.
- Inventory all relevant source files, project-local OpenCode configs and mounted/global files, including `~/.config/opencode/opencode.json`, `opencode.jsonc`, `tui.json(c)`, `cli.json` and projects' `opencode.json(c)` and `.opencode/` contents. Check precedence and `XDG_CONFIG_HOME`.
- Back up any writable **global user config** before mutation, preserving permissions, and verify backups. Preserve secrets, environment references, provider credentials, tokens, MCP secrets, session databases and state. **Never commit global config, credentials, session history or backups to Git**.
- The launcher already bind-mounts `~/.agents`, `~/.config/opencode`, `~/.local/share/opencode`, `~/.local/state/opencode` and `~/.cache/opencode`. Retain appropriate persistence.
- If the host-global files are not actually accessible in this container/session, complete the repository-side changes and provide exact safe migration commands/instructions for the unavailable global files. Never fabricate their content or claim they were migrated.
- Do not gratuitously run commands that destroy persistent state. Remember V2 may migrate a database: an image downgrade alone cannot restore the prior schema.

## Repo-side changes

### Containerfile

- Replace `opencode-ai` in the npm package list with `@opencode/cli`; adjust npm `allow-scripts` for the current V2 postinstall/native binary.
- Verify the final executable path used in `src/ai_container/cli.py` (currently `/usr/local/bin/opencode`) actually exists after installation. Preserve the default entrypoint semantics.
- Audit `@ramtinj95/opencode-tokenscope` and any other OpenCode-only extensions: port/upgrade incompatible integrations, or remove with explicit rationale when V2 offers the same facility. Do not leave a plugin silently broken.
- Audit at least `gopls`, `lua-language-server`, `terraform-ls`, `rust-analyzer`, `lemminx`, `ruby-lsp`, `perlnavigator-server`, `pyright`, `typescript-language-server`, `yaml-language-server`, `bash-language-server`, `intelephense`, `vscode-langservers-extracted`, `taplo` and `clang-tools/clangd`. Remove LSP-only packages and their download/installation steps, including bespoke rust-analyzer and lemminx blocks, if not used for anything else. Keep useful language runtimes, compiler tools, `typescript`, linters, formatters and QA dependencies. Check usage before removing any package.
- Remove stale OpenCode LSP settings and `OPENCODE_DISABLE_LSP_DOWNLOAD` examples once no longer meaningful.

### Host launcher and standalone server

- Inspect `src/ai_container/cli.py`, `src/ai_container/web.py`, `tests/test_cli.py`, `tests/test_web.py` and other usages. Prefer renaming the Python web module/test to `server.py`/`test_server.py` as part of the public rename if the resulting diff stays coherent.
- Replace public `--web`, `--web-port`, `--web-username` and `--web-password` flags with `--server`, `--server-port`, `--server-username` and `--server-password`. Retain the existing port default unless there is a compelling reason to change it. Preserve support for Podman, Docker and Apple's `container` tool.
- Launch `opencode serve --hostname 0.0.0.0 --port <port>` in a detached container, publish the chosen port, and preserve working username/password authentication using **V2-supported** settings (verify what authentication mechanisms V2 actually uses). Do not claim a flag or env var works without checking.
- Keep the distinction clear: `ai-container --server` is the host wrapper mode; `opencode --server URL` is a native V2 client option for connecting to a remote server, and `opencode serve` starts the server.
- Update wrapper conflict checks (`--init`, `--shell`, assistant shortcuts, `--entrypoint`), docs, debug messages, unit tests and port/credential displays. Decide whether a deprecated old flag should fail explicitly with a helpful error, so it is not accidentally forwarded as an unknown OpenCode option.
- Do not break ordinary interactive `ai-container`, `ai-container --claude`, `--codex`, `--copilot`, `--shell`, `--init`, extra mounts, environment forwarding, SELinux and other launch features.

### Full native V2 configuration migration: `opencode.json`

Read **the entire real configuration** (global and project-level) and transform deliberately to native V2, not merely 'V1 accepted by V2'. Verify all relevant fields, including:

- `plugin` → `plugins` and package/options tuples → descriptors.
- `agent` and legacy modes → `agents`; `prompt` → `system`, `disable` → `disabled`, model `variant` suffix, request/steps and nested permissions.
- `command` → `commands`; `subtask` → `subagent`; preserve file-based commands.
- `provider` → `providers`, npm SDK package IDs, endpoints, API-key environment references, model options/variants.
- V1 MCP map → `mcp.servers`, invert `enabled` to `disabled`, update timeout catalog/execution and OAuth field names.
- V1 `skills.paths`/`skills.urls` → ordered V2 `skills` array while keeping skills and IDs discoverable.
- `permission`/`tools` → ordered native V2 `permissions` with correct tool/action names and precedence; preserve **explicit** restrictions.
- `snapshot` → `snapshots`, `attachment` → `media`, `reference` → `references`, and compaction settings.
- Inspect all remaining values and unsupported legacy keys; remove only after understanding their former purpose. Avoid mixed V1/V2 syntax within a single agent/provider/command/model entry. Validate against native V2 schema and effective config.
- **Permission preference:** Do **not** emulate V1's default request for paths outside the project. The user wants V2's native default for `external_directory`. Do not add `external_directory: ask` simply for backward compatibility, but don't throw away deliberate user-authored restrictions elsewhere.

### TUI configuration migration: `tui.json(c)` → `cli.json`

- Read the user's existing `tui.json` or `tui.jsonc` and any project-local files. V2 has a **single global** `~/.config/opencode/cli.json`, not project-local CLI settings.
- Preserve supported themes, keybindings, display and terminal preferences, notifications, plugins and any other relevant CLI preferences. If `cli.json` already exists, reconcile settings instead of overwriting.
- Project-local V1 TUI preferences should be evaluated and sensibly merged into global settings; report irreconcilable conflicting per-project preferences, without silently dropping them.
- Use `"$schema": "https://opencode.ai/v2/cli.json"` where supported, and native V2 keys. Explicitly validate that `cli.json` is strict JSON accepted by V2. Back up, then retire or rename legacy `tui.json(c)` files after verifying migration.

### Strict JSON policy (explicit requirement)

- Search the full repository for `*.jsonc` and search global/mounted OpenCode configuration for `*.jsonc` before and after changes.
- Rename converted OpenCode server config to `opencode.json`; migrate terminal config into `cli.json`. Convert **all other repository-owned `*.jsonc`** to equivalent `*.json` when possible. Do not just rename an unparsed JSONC file: parse JSONC, serialize valid JSON (no comments/trailing commas), and ensure semantic equivalence. Respect duplicate keys and warn or resolve them rather than silently losing data.
- **Remove commented-out settings from actual configuration files.** For each migrated `opencode.jsonc`, `tui.jsonc`, or other JSONC config, keep only enabled/active entries in output. Treat disabled JSONC entries and blocks as dead configuration: delete them altogether, even if they contain potentially useful defaults. Do not convert them to active values, and do not copy them to Markdown. Preserve only essential plain-language explanation of active settings where needed.
- Preserve necessary human annotations about active behavior in Markdown, and update every file/path reference, checks, manifests, build step and test fixture. Don't generate a spurious `tui.json` when the target should be `cli.json`.
- At the end, assert that `find . -type f -name '*.jsonc'` (excluding ignored/generated build environments) finds none, and all changed/new `*.json` parse with `jq` or a strict JSON parser. Also check global OpenCode `*.jsonc` is retired where accessible.

## Integrations, plugins, skills and init.sh

- Audit global and local V1 plugins and rework their implementation for V2. V1 plugins need **code changes**: a config-key rename alone is insufficient. Check server plugin and TUI plugin entrypoints, hook signatures, tool registration and packages.
- Examine the existing `.opencode/plugins/graphify.js`, which already exports V1 `server()` and V2 `setup()`. Retain and verify the V2 behavior (including session-scoped command interception and unique plugin IDs); remove V1-only code only after tests pass.
- Check `init.sh`, the skill installer (`-a opencode`), OpenQA, openSUSE packaging, design-taste-frontend, Caveman, RTK, Graphify and SkillSpector. Ensure repeatable `ai-container --init` does not erase user configuration.
- Especially examine SkillSpector's `~/.config/opencode/commands/skillspector.md` and legacy `~/.config/opencode/tools/skillspector_scan*.ts`: V2 custom tools may need to be registered through a V2 plugin. Port if needed, preserve `/skillspector` functionality, and test.
- Verify installed plugins, skill discovery, subagents, commands, MCP connectivity, and reasonable default model/credentials behavior. Report third-party plugins without available V2 versions accurately.

## Validation and delivery

- Update README usage and examples, `ai-container.toml.example`, `AGENTS.md` where necessary, all related tests, and any docs containing obsolete `--web` flags, `web mode` names, V1 package instructions, LSP-only descriptions, `tui.json(c)` references, or `*.jsonc` references to actual files. Upstream reference docs may still mention JSONC: that's fine when describing external capabilities, but repository *files* should be JSON.
- Run `uv run ruff format .`, `uv run ruff check .`, `uv run mypy`, `uv run pytest`; diagnose and fix failures. Verify the container build when a supported container runtime is available; if unavailable, explicitly say so rather than inventing successful output.
- Check `opencode --version`, `opencode --help`, `opencode serve --help`, available config/plugin/MCP inspection commands, and validate configuration using V2 (if installed). Don't make up command names.
- Test representative launcher invocations and conflict cases on all runtimes to the extent practical.
- Review the final diff and `git status`. Keep this prompt file in the repository. Do not commit the user's private OpenCode config/credentials, and do not automatically commit unrelated changes.
- In your final response provide: (a) summary of changed repo files; (b) what happened to *both* OpenCode config files and any project/global `*.jsonc`; (c) removed vs retained LSP tooling with reasons; (d) plugin/skill issues; (e) exact tests/verification and failures; (f) backup and rollback instructions; (g) any remaining manual steps.
