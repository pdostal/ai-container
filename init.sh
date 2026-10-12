#!/bin/bash
set -euo pipefail

step() {
    printf '\n==> %s\n' "$1"
}

step "Installing the openQA skill"
npx -y skills add os-autoinst/openQA-skill --skill openqa -g -a opencode -y
npx -y skills add os-autoinst/openQA-skill --skill openqa -g -a claude-code -y

step "Installing the openSUSE packaging skill"
npx -y skills add openSUSE/openSUSE-packaging-skill --skill opensuse-packaging -g -a opencode -y
npx -y skills add openSUSE/openSUSE-packaging-skill --skill opensuse-packaging -g -a claude-code -y

step "Installing the frontend design skill"
npx -y skills add Leonxlnx/taste-skill --skill design-taste-frontend -g -a opencode -y
npx -y skills add Leonxlnx/taste-skill --skill design-taste-frontend -g -a claude-code -y

step "Installing Caveman"
npx -y skills add JuliusBrussee/caveman -g --skill caveman -a opencode -y
npx -y skills add JuliusBrussee/caveman -g --skill caveman -a claude-code -y

step "Configuring RTK"
rtk init -g --opencode

step "Configuring Graphify"
graphify install --platform=claude
graphify install --platform=opencode

step "Installing the SkillSpector OpenCode extension"
install -Dm644 /usr/local/share/skillspector/opencode/commands/skillspector.md "$HOME/.config/opencode/commands/skillspector.md"
install -Dm644 /usr/local/share/skillspector/opencode/tools/skillspector_scan.ts "$HOME/.config/opencode/tools/skillspector_scan.ts"
install -Dm644 /usr/local/share/skillspector/opencode/tools/skillspector_scan_lib.ts "$HOME/.config/opencode/tools/skillspector_scan_lib.ts"

printf '\nInitialization complete.\n'
