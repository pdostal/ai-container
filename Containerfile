FROM registry.opensuse.org/opensuse/tumbleweed:latest
ARG CODER_UID=1000
ARG CODER_GID=1000
RUN zypper ar --no-gpgcheck --refresh --priority 95 http://download.suse.de/ibs/QA:/Maintenance/openSUSE_Tumbleweed/QA:Maintenance.repo && zypper -n in ca-certificates-suse osc-plugin-qam || true
# Community-maintained Swift toolchain repo (not packaged by openSUSE upstream); needed for sourcekit-lsp.
RUN zypper ar --no-gpgcheck --refresh --priority 95 https://download.opensuse.org/repositories/home:/mgrossu/openSUSE_Tumbleweed/home:mgrossu.repo
RUN zypper -n in git-core git-lfs gh glab gitea-tea bat less cnf cnf-bash openssh-clients gpg2 command-not-found hostname -busybox-hostname openQA-client spec-cleaner rpmlint osc obs-service-* \
    python3 python3-pip python3-pipx python3-uv perl perl-Perl-Tidy ShellCheck npm jq python313-ruff python313-flake8 python313-yamllint yq iputils forgejo-cli kubernetes-client kustomize \
    gitea-tea golangci-lint python313-gitlint aws-cli python313-pylint python313-pytest-pylint perl-Mojolicious os-autoinst-distri-opensuse-deps os-autoinst-devel perl-Test-Exception \
    perl-Test-Fatal perl-Test-MockModule perl-Test-MockObject perl-Test-Warnings expect go1.27 cargo rust unzip ripgrep \
    gopls lua-language-server clang-tools ruby taplo java-21-openjdk-headless php8 swift-lang \
    php8-ctype php8-curl php8-dom php8-fileinfo php8-gd \
    php8-mbstring php8-openssl php8-pdo php8-posix php8-zip php8-zlib \
    php8-bz2 php8-iconv php8-imagick php8-intl php8-pcntl php8-redis \
    php8-xmlreader php8-xmlwriter php8-sqlite php8-tokenizer php8-phar \
    php-composer2 php8-smbclient php8-ldap php8-mysql php8-pgsql
RUN gem install ruby-lsp
RUN npm install -g markdownlint-cli perlnavigator-server \
    pyright typescript typescript-language-server yaml-language-server bash-language-server intelephense vscode-langservers-extracted
# Reuse an existing group when CODER_GID already exists in the base image.
RUN if getent group "${CODER_GID}" >/dev/null; then \
      group_name="$(getent group "${CODER_GID}" | cut -d: -f1)"; \
    else \
      groupadd -g "${CODER_GID}" coder; \
      group_name=coder; \
    fi; \
    useradd -u "${CODER_UID}" -g "${group_name}" -m -d /home/coder coder
RUN printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/xdg-open && chmod +x /usr/local/bin/xdg-open
RUN mkdir -p \
      /home/coder/.config/gcloud \
      /home/coder/.config/openqa \
      /home/coder/.gnupg \
      /home/coder/.ssh/agent \
      /etc/ssh/ssh_config.d
COPY 99-ai-container.conf /etc/ssh/ssh_config.d/99-ai-container.conf
RUN chown -R coder:$(id -gn coder) /home/coder
WORKDIR /home/coder
USER coder
RUN cargo install bugwarden ruoqa-mcp --locked && \
    cargo install --git https://github.com/mimi1vx/ruprogress-mcp --locked ruprogress-mcp
RUN GOPROXY=direct go install github.com/github/github-mcp-server/cmd/github-mcp-server@latest
RUN GOPROXY=direct go install github.com/hashicorp/terraform-ls@latest
# rust-analyzer has no distro/cargo/npm-installable release; grab the latest prebuilt binary.
RUN mkdir -p /home/coder/.local/bin && \
    curl -fsSL https://github.com/rust-lang/rust-analyzer/releases/latest/download/rust-analyzer-x86_64-unknown-linux-gnu.gz | gunzip -c > /home/coder/.local/bin/rust-analyzer && \
    chmod +x /home/coder/.local/bin/rust-analyzer
# lemminx (XML LSP) isn't published standalone; extract its uber jar from the official VS Code extension.
RUN mkdir -p /home/coder/.local/share/lemminx && \
    curl -fsSL "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/redhat/vsextensions/vscode-xml/latest/vspackage" | gunzip -c > /tmp/vscode-xml.vsix && \
    unzip -p /tmp/vscode-xml.vsix extension/server/org.eclipse.lemminx-uber.jar > /home/coder/.local/share/lemminx/lemminx.jar && \
    rm -f /tmp/vscode-xml.vsix
RUN curl -fsSL https://claude.ai/install.sh | bash
RUN curl -fsSL https://opencode.ai/install | bash
ENV PATH="/home/coder/.local/bin:$PATH"
