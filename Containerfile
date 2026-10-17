FROM registry.opensuse.org/opensuse/tumbleweed:latest
ARG CODER_UID=1000
ARG CODER_GID=1000
RUN zypper -n ref && echo -en "\n\n\n" && zypper -n in git-core git-lfs git-filter-repo spec-cleaner rpmlint osc tilth bugwarden \
    python314 python314-pip python314-pipx python314-uv perl perl-Perl-Tidy python314-flake8 python314-yamllint kubernetes-client \
    golangci-lint python313-gitlint aws-cli python314-pylint python314-pytest-pylint perl-Mojolicious perl-Test-Exception jq yq \
    perl-Test-Fatal perl-Test-MockModule perl-Test-MockObject perl-Test-Warnings expect go1.27 cargo rust unzip ripgrep npm26 \
    gopls lua-language-server clang-tools ruby taplo java-21-openjdk-headless php8 os-autoinst-distri-opensuse-deps nodejs26 bat \
    php8-ctype php8-curl php8-dom php8-fileinfo php8-gd skillspector skillspector-mcp os-autoinst-devel python314-ruff iputils \
    php8-mbstring php8-openssl php8-pdo php8-posix php8-zip php8-zlib ShellCheck forgejo-cli kustomize gitleaks gh glab gitea-tea \
    php8-bz2 php8-iconv php8-imagick php8-intl php8-pcntl php8-redis less cnf cnf-bash openssh-clients hostname openQA-client \
    php8-xmlreader php8-xmlwriter php8-sqlite php8-tokenizer php8-phar perl-Mojo-SQLite perl-Minion-Backend-SQLite skillspector \
    php-composer2 php8-smbclient php8-ldap php8-mysql php8-pgsql rtk openai-codex pi-coding-agent skillspector-mcp opentofu \
    perl-SQL-SplitStatement os-autoinst obs-service-verify_file obs-service-update_changelog obs-service-tar_scm obs-service-tar \
		obs-service-source_validator obs-service-set_version obs-service-recompress obs-service-obs_scm-common obs-service-obs_scm \
		obs-service-go_modules obs-service-format_spec_file obs-service-download_files obs-service-cargo obs-service-extract_file \
		obs-service-download_assets obs-service-download_url obs-service-kiwi_label_helper obs-service-kiwi_metainfo_helper \
		obs-service-node_modules obs-service-compose_kiwi_description obs-service-docker_label_helper obs-service-update_changelog \
		obs-service-post_build_checks_containers
RUN zypper ar --no-gpgcheck --refresh --priority 95 http://download.suse.de/ibs/QA:/Maintenance/openSUSE_Tumbleweed/QA:Maintenance.repo && echo -en "\n\n\n" && zypper -n in ca-certificates-suse osc-plugin-qam ruprogress-mcp ruoqa-mcp || true
#RUN zypper ar --no-gpgcheck --refresh --priority 95 https://download.opensuse.org/repositories/home:/mgrossu/openSUSE_Tumbleweed/home:mgrossu.repo && echo -en "\n\n\n" && zypper -n in swift-lang || true
RUN gem install ruby-lsp
RUN npm config set fund false \
    && npm config set allow-scripts=protobufjs,core-js,opencode-ai,msgpackr-extract --location=user && npm install -g npm@latest \
    && npm install -g markdownlint-cli perlnavigator-server openrtk @ramtinj95/opencode-tokenscope opencode-ai pyright \
		typescript typescript-language-server yaml-language-server bash-language-server intelephense vscode-langservers-extracted @github/copilot
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
RUN chmod 644 /etc/ssh/ssh_config.d/99-ai-container.conf
RUN chown -R coder:$(id -gn coder) /home/coder
RUN export GOBIN=/usr/local/bin && \
    go install github.com/github/github-mcp-server/cmd/github-mcp-server@latest && \
    go install github.com/hashicorp/terraform-ls@latest
WORKDIR /home/coder
USER coder
ENV PATH="/home/coder/.local/bin:${PATH}"
# rust-analyzer has no distro/cargo/npm-installable release; grab the latest prebuilt binary.
RUN mkdir -p /home/coder/.local/bin && \
    curl -fsSL https://github.com/rust-lang/rust-analyzer/releases/latest/download/rust-analyzer-$(uname -m)-unknown-linux-gnu.gz | gunzip -c > /home/coder/.local/bin/rust-analyzer && \
    chmod +x /home/coder/.local/bin/rust-analyzer
# lemminx (XML LSP) isn't published standalone; extract its uber jar from the official VS Code extension.
RUN mkdir -p /home/coder/.local/share/lemminx && \
    curl -fsSL "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/redhat/vsextensions/vscode-xml/latest/vspackage" | gunzip -c > /tmp/vscode-xml.vsix && \
    unzip -p /tmp/vscode-xml.vsix extension/server/org.eclipse.lemminx-uber.jar > /home/coder/.local/share/lemminx/lemminx.jar && \
    rm -f /tmp/vscode-xml.vsix
RUN curl -fsSL https://claude.ai/install.sh | bash
RUN uv tool install graphifyy
RUN uv tool install git+https://github.com/NVIDIA/skillspector.git@v2.12.0
