FROM registry.opensuse.org/opensuse/tumbleweed:latest
ARG CODER_UID=1000
ARG CODER_GID=1000
# Native install scripts npm 12 is allowed to run. Pi installs packages as the
# coder user, so this list is applied to both root and coder below.
ARG NPM_ALLOW_SCRIPTS=protobufjs,core-js,@opencode/cli,msgpackr-extract,node-pty,@ast-grep/cli,tree-sitter-bash,pi-memory
RUN zypper -n ref && echo -en "\n\n\n" && zypper -n install --allow-downgrade --allow-arch-change --allow-vendor-change \
    git-core git-lfs git-filter-repo spec-cleaner rpmlint osc tilth bugwarden \
    python314 python314-pip python314-pipx python314-uv perl perl-Perl-Tidy python314-flake8 python314-yamllint kubernetes-client \
    golangci-lint python313-gitlint aws-cli azure-cli perl-Mojolicious perl-Test-Exception jq yq \
    perl-Test-Fatal perl-Test-MockModule perl-Test-MockObject perl-Test-Warnings expect go1.27 cargo rust unzip ripgrep npm26 \
    clang-tools make gcc-c++ python3 ruby taplo php8 os-autoinst-distri-opensuse-deps nodejs26 bat knot knot-utils chromium \
    php8-ctype php8-curl php8-dom php8-fileinfo php8-gd skillspector skillspector-mcp os-autoinst-devel python314-ruff iputils \
    php8-mbstring php8-openssl php8-pdo php8-posix php8-zip php8-zlib ShellCheck forgejo-cli kustomize gitleaks gh glab gitea-tea \
    php8-bz2 php8-iconv php8-imagick php8-intl php8-pcntl php8-redis less cnf cnf-bash openssh-clients hostname openQA-client \
    php8-xmlreader php8-xmlwriter php8-sqlite php8-tokenizer php8-phar perl-Mojo-SQLite perl-Minion-Backend-SQLite skillspector \
    php-composer2 php8-smbclient php8-ldap php8-mysql php8-pgsql rtk openai-codex pi-coding-agent \
    pi-coding-agent-examples socat skillspector-mcp opentofu openqa-mon bc ipcalc ImageMagick \
    perl-SQL-SplitStatement os-autoinst obs-service-verify_file obs-service-update_changelog obs-service-tar_scm obs-service-tar \
    obs-service-source_validator obs-service-set_version obs-service-recompress obs-service-obs_scm-common obs-service-obs_scm \
    obs-service-go_modules obs-service-format_spec_file obs-service-download_files obs-service-cargo obs-service-extract_file \
    obs-service-download_assets obs-service-download_url obs-service-kiwi_label_helper obs-service-kiwi_metainfo_helper \
    obs-service-node_modules obs-service-compose_kiwi_description obs-service-docker_label_helper obs-service-update_changelog \
    obs-service-post_build_checks_containers helm \
    postgresql-server perl-App-cpanminus \
    perl-DBIx-Class perl-DBIx-Class-DeploymentHandler perl-DBIx-Class-DynamicDefault \
    perl-DBIx-Class-OptimisticLocking perl-DBIx-Class-Schema-Config \
    perl-DBD-Pg perl-DateTime-Format-Pg perl-Mojo-Pg perl-Minion perl-SQL-Translator \
    perl-Mojolicious-Plugin-AssetPack perl-Mojolicious-Plugin-OAuth2 \
    perl-CSS-Minifier-XS perl-JavaScript-Minifier-XS perl-CSS-Sass \
    perl-Mojo-RabbitMQ-Client perl-Net-OpenID-Consumer perl-CommonMark perl-CryptX \
    perl-BSD-Resource perl-File-Copy-Recursive perl-Pod-POM perl-Sort-Versions \
    perl-Time-modules perl-aliased perl-MCP perl-Devel-Cover-Report-Codecovbash \
    perl-Selenium-Remote-Driver chromedriver perl-TAP-Harness-JUnit perl-Pod-Markdown \
    perl-Test-Output perl-TAP-Harness-JUnit perl-Pod-Markdown perl-App-cpanminus \
    perl-Devel-Cover-Report-Codecovbash
# The October 2026 TLS fixes (NSS 3.131.1 roots, compromised eMudhra CA dropped)
# start at nodejs26 26.12.1, and Tumbleweed still ships 26.12.0, which makes
# Plannotator warn on every pi start. Take the devel repo's 26.13.1: npm26 pins
# nodejs26 to its exact version, so both move together. The gate catches a
# downgrade; the ABI (libnode.so.147) is unchanged, so compiled modules still load.
RUN zypper -n ar --no-gpgcheck --refresh --priority 90 https://download.opensuse.org/repositories/devel:/languages:/nodejs/openSUSE_Tumbleweed/ devel:languages:nodejs \
    && zypper -n in --allow-vendor-change --from devel:languages:nodejs nodejs26 npm26 \
    && node -e 'const [a, b, c] = process.versions.node.split(".").map(Number); if (a === 26 && (b < 12 || (b === 12 && c < 1))) throw new Error(`node ${process.versions.node} lacks the October 2026 TLS fixes`);'
RUN zypper ar --no-gpgcheck --refresh --priority 95 http://download.suse.de/ibs/QA:/Maintenance/openSUSE_Tumbleweed/QA:Maintenance.repo && echo -en "\n\n\n" && zypper -n in ca-certificates-suse osc-plugin-qam ruprogress-mcp ruoqa-mcp || true
#RUN zypper ar --no-gpgcheck --refresh --priority 95 https://download.opensuse.org/repositories/home:/mgrossu/openSUSE_Tumbleweed/home:mgrossu.repo && echo -en "\n\n\n" && zypper -n in swift-lang || true
RUN npm config set fund false \
    && npm config set allow-scripts="${NPM_ALLOW_SCRIPTS}" --location=user && npm install -g npm@latest \
    && npm install -g markdownlint-cli openrtk @opencode/cli pyright typescript @github/copilot @playwright/mcp @tobilu/qmd \
    && test -x /usr/local/bin/opencode && test -x /usr/local/bin/qmd
# Reuse an existing group when CODER_GID already exists in the base image.
RUN if getent group "${CODER_GID}" >/dev/null; then \
      group_name="$(getent group "${CODER_GID}" | cut -d: -f1)"; \
    else \
      groupadd -g "${CODER_GID}" coder; \
      group_name=coder; \
    fi; \
    useradd -u "${CODER_UID}" -g "${group_name}" -m -d /home/coder coder
RUN printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/xdg-open && chmod +x /usr/local/bin/xdg-open
RUN mkdir -p /etc/ssh/ssh_config.d
COPY 99-ai-container.conf /etc/ssh/ssh_config.d/99-ai-container.conf
COPY --chmod=755 init.sh /usr/local/bin/init.sh
COPY --chmod=755 opencode/launch.sh /usr/local/bin/opencode-launch
COPY --chmod=755 pi/print.sh /usr/local/bin/pi-print
COPY --chmod=644 pi/print-mode-extensions /usr/local/share/pi/print-mode-extensions
COPY --chmod=644 pi/compact-messages.js /usr/local/share/pi/extensions/compact-messages.js
COPY --chmod=644 pi/skillspector.js /usr/local/share/pi/extensions/skillspector.js
COPY --chmod=755 scripts/patch_pi_mcp_adapter.py /usr/local/bin/pi-mcp-adapter-static-import
COPY skillspector/plugin.js /usr/local/share/skillspector/opencode/plugins/skillspector.js
COPY skillspector/skillspector.md /usr/local/share/skillspector/opencode/commands/skillspector.md
COPY opencode/rtk-v2.js /usr/local/share/opencode/rtk-v2.js
COPY opencode/caveman-v2.js /usr/local/share/opencode/caveman-v2.js
RUN chmod 644 /etc/ssh/ssh_config.d/99-ai-container.conf
# Mount target for the host-side $TMPDIR cache directory.
RUN mkdir -p /home/coder/.cache/tmp
RUN chown -R coder:$(id -gn coder) /home/coder
RUN export GOBIN=/usr/local/bin && \
    go install github.com/github/github-mcp-server/cmd/github-mcp-server@latest
RUN rm -rf /tmp/opencode /tmp/.bun-0-*.so /tmp/node-compile-cache
WORKDIR /home/coder
USER coder
ENV PATH="/home/coder/.local/bin:${PATH}"
# Everything per-start perf depends on lives under $TMPDIR: jiti (pi's extension
# loader) keeps its transpile cache there, Node its module-compile cache, and
# pi-subagents and pyright their state. A fresh container's filesystem is thrown
# away on exit, so the launcher bind-mounts the whole directory from the host
# (see PI_CACHE_MOUNTS in src/ai_container/defaults.py): otherwise pi
# re-transpiles every extension on every start (~57s instead of ~4s).
# NODE_COMPILE_CACHE is what makes the compile-cache half of that work -- without
# it Node caches nothing there, and pi's ~3.8s of extension imports is V8
# compiling ~10MB of bundles. Worth ~0.5s per start, for every Node tool in here.
ENV TMPDIR=/home/coder/.cache/tmp
ENV NODE_COMPILE_CACHE=/home/coder/.cache/tmp/node-compile-cache
# pi's powerline footer falls back to ASCII icons ("dir" instead of a folder
# glyph) unless this is set: it infers Nerd Font support from TERM_PROGRAM/TERM,
# and here TERM=xterm-256color with no TERM_PROGRAM never matches. It cannot come
# from a shell rc file either -- pi is started by podman-init, not by a shell.
ENV POWERLINE_NERD_FONTS=1
# Pi runs npm installs as coder under ~/.pi/agent/npm; give that user the same
# allowlist so native modules such as node-pty compile instead of being skipped.
RUN npm config set allow-scripts="${NPM_ALLOW_SCRIPTS}" --location=user
RUN curl -fsSL https://claude.ai/install.sh | bash
RUN uv tool install graphifyy
RUN uv tool install git+https://github.com/NVIDIA/skillspector.git@v2.12.0
