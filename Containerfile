FROM registry.opensuse.org/opensuse/tumbleweed:latest
ARG CODER_UID=1000
ARG CODER_GID=1000
RUN zypper ar --no-gpgcheck --refresh --priority 95 http://download.suse.de/ibs/QA:/Maintenance/openSUSE_Tumbleweed/QA:Maintenance.repo && zypper -n in ca-certificates-suse osc-plugin-qam || true
RUN zypper -n in git-core git-lfs gh glab gitea-tea bat less cnf cnf-bash openssh-clients gpg2 command-not-found \
    python3 python3-pip python3-pipx python3-uv perl perl-Perl-Tidy ShellCheck npm jq python313-ruff python313-flake8 python313-yamllint \
    yq iputils forgejo-cli kubernetes-client kustomize gitea-tea osc obs-service-* golangci-lint python313-gitlint openQA-client
RUN npm install -g markdownlint-cli
# Reuse an existing group when CODER_GID already exists in the base image.
RUN if getent group "${CODER_GID}" >/dev/null; then \
      group_name="$(getent group "${CODER_GID}" | cut -d: -f1)"; \
    else \
      groupadd -g "${CODER_GID}" coder; \
      group_name=coder; \
    fi; \
    useradd -u "${CODER_UID}" -g "${group_name}" -m -d /home/coder coder
RUN mkdir -p \
      /home/coder/.config/gcloud \
      /home/coder/.config/openqa \
      /home/coder/.gnupg \
      /home/coder/.ssh/agent \
      /workdir
RUN chown -R coder:$(id -gn coder) /home/coder /workdir
WORKDIR /workdir
USER coder
RUN curl -fsSL https://claude.ai/install.sh | bash
RUN curl -fsSL https://opencode.ai/install | bash
ENV PATH="/home/coder/.local/bin:$PATH"
