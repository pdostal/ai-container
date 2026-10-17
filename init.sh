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
if [ ! -f "$HOME/.config/opencode/plugins/caveman-v2.js" ]; then
    install -Dm644 /usr/local/share/opencode/caveman-v2.js "$HOME/.config/opencode/plugins/caveman-v2.js"
fi

step "Configuring RTK"
if [ ! -f "$HOME/.config/opencode/plugins/rtk-v2.js" ]; then
    install -Dm644 /usr/local/share/opencode/rtk-v2.js "$HOME/.config/opencode/plugins/rtk-v2.js"
fi

step "Configuring Graphify"
graphify install --platform=claude
graphify install --platform=opencode

step "Installing the SkillSpector OpenCode extension"
for file in /usr/local/share/skillspector/opencode/commands/skillspector.md /usr/local/share/skillspector/opencode/plugins/skillspector.js; do
    target="$HOME/.config/opencode/${file#/usr/local/share/skillspector/opencode/}"
    if [ ! -e "$target" ]; then
        install -Dm644 "$file" "$target"
    fi
done

printf '\nInitialization complete.\n'
