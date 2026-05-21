FROM registry.opensuse.org/opensuse/tumbleweed:latest
RUN zypper -n in git-core git-lfs gh glab gitea-tea bat less cnf cnf-bash \
    python3 python3-pip python3-uv \
    python313-ruff python313-flake8 python313-yamllint \
    perl perl-Perl-Tidy \
    ShellCheck npm \
    gpg2 openssh-clients
RUN npm install -g markdownlint-cli
RUN useradd -d /home/pdostal pdostal
RUN mkdir -p /home/pdostal/.ssh/agent
RUN chown -R pdostal:pdostal /home/pdostal
RUN mkdir /workdir
WORKDIR /workdir
USER pdostal
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/home/pdostal/.local/bin:$PATH"
