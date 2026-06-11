FROM registry.opensuse.org/opensuse/tumbleweed:latest
RUN zypper ar --no-gpgcheck --refresh --priority 95 http://download.suse.de/ibs/QA:/Maintenance/openSUSE_Tumbleweed/QA:Maintenance.repo
RUN zypper -n in git-core git-lfs gh glab gitea-tea bat less cnf cnf-bash openssh-clients gpg2 ca-certificates-suse command-not-found \
    python3 python3-pip python3-pipx python3-uv perl perl-Perl-Tidy ShellCheck npm jq python313-ruff python313-flake8 python313-yamllint \
    yq iputils forgejo-cli kubernetes-client kustomize gitea-tea osc obs-service-* osc-plugin-qam python313-gitlint
RUN npm install -g markdownlint-cli
RUN useradd -d /home/pdostal pdostal
RUN mkdir -p /home/pdostal/.ssh/agent
RUN chown -R pdostal:pdostal /home/pdostal
RUN mkdir /workdir
WORKDIR /workdir
USER pdostal
RUN curl -fsSL https://claude.ai/install.sh | bash
RUN curl -fsSL https://opencode.ai/install | bash
ENV PATH="/home/pdostal/.local/bin:$PATH"
