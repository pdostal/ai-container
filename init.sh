#!/bin/bash
set -euo pipefail

step() {
    printf '\n==> %s\n' "$1"
}

step "Installing the openQA skill"
npx -y skills add os-autoinst/openQA-skill --skill openqa -g -a opencode -y
npx -y skills add os-autoinst/openQA-skill --skill openqa -g -a claude-code -y
npx -y skills add os-autoinst/openQA-skill --skill openqa -g -a pi -y

step "Installing the openSUSE packaging skill"
npx -y skills add openSUSE/openSUSE-packaging-skill --skill opensuse-packaging -g -a opencode -y
npx -y skills add openSUSE/openSUSE-packaging-skill --skill opensuse-packaging -g -a claude-code -y
npx -y skills add openSUSE/openSUSE-packaging-skill --skill opensuse-packaging -g -a pi -y

step "Installing the frontend design skill"
npx -y skills add Leonxlnx/taste-skill --skill design-taste-frontend -g -a opencode -y
npx -y skills add Leonxlnx/taste-skill --skill design-taste-frontend -g -a claude-code -y
npx -y skills add Leonxlnx/taste-skill --skill design-taste-frontend -g -a pi -y

step "Installing Caveman"
npx -y skills add JuliusBrussee/caveman -g --skill caveman -a opencode -y
npx -y skills add JuliusBrussee/caveman -g --skill caveman -a claude-code -y
npx -y skills add JuliusBrussee/caveman -g --skill caveman -a pi -y
if [ ! -f "$HOME/.config/opencode/plugins/caveman-v2.js" ]; then
    install -Dm644 /usr/local/share/opencode/caveman-v2.js "$HOME/.config/opencode/plugins/caveman-v2.js"
fi

step "Configuring RTK"
if [ ! -f "$HOME/.config/opencode/plugins/rtk-v2.js" ]; then
    install -Dm644 /usr/local/share/opencode/rtk-v2.js "$HOME/.config/opencode/plugins/rtk-v2.js"
fi
if [ ! -e "$HOME/.pi/agent/extensions/rtk.ts" ]; then
    rtk init --global --agent pi --no-patch
fi

step "Configuring Graphify"
graphify install --platform=claude
graphify install --platform=opencode
graphify install --platform=pi

step "Configuring pi"
mkdir -p "$HOME/.pi/agent"
pi_settings="$HOME/.pi/agent/settings.json"
if [ ! -e "$pi_settings" ]; then
    printf '{\n  "quietStartup": true\n}\n' > "$pi_settings"
elif ! jq -e '.quietStartup != null' "$pi_settings" >/dev/null; then
    tmp="$(mktemp)"
    jq '.quietStartup = true' "$pi_settings" > "$tmp"
    chmod --reference="$pi_settings" "$tmp"
    mv "$tmp" "$pi_settings"
fi
if [ ! -e "$HOME/.pi/agent/extensions/compact-messages.js" ]; then
    install -Dm644 /usr/local/share/pi/extensions/compact-messages.js \
        "$HOME/.pi/agent/extensions/compact-messages.js"
fi
# Seeded so it can be edited; `pi-print` falls back to the image copy if absent.
if [ ! -e "$HOME/.pi/print-mode-extensions" ]; then
    install -Dm644 /usr/local/share/pi/print-mode-extensions \
        "$HOME/.pi/print-mode-extensions"
fi

step "Repairing native npm modules"
node_pty="$HOME/.pi/agent/npm/node_modules/node-pty"
if [ -d "$node_pty" ]; then
    node_pty_platform="$(node -p 'process.platform + "-" + process.arch')"
    if [ ! -e "$node_pty/build/Release/pty.node" ] && \
        [ ! -e "$node_pty/prebuilds/$node_pty_platform/pty.node" ]; then
        printf 'Rebuilding node-pty for %s...\n' "$node_pty_platform"
        if ! (cd "$HOME/.pi/agent/npm" && npm rebuild node-pty --foreground-scripts); then
            printf 'warning: node-pty rebuild failed; Plannotator PTY features may be unavailable\n' >&2
        fi
    fi
fi

step "Patching pi-mcp-adapter's built-in MCP turn-off"
adapter="$HOME/.pi/agent/npm/node_modules/pi-mcp-adapter/index.ts"
if [ -f "$adapter" ] && pi-mcp-adapter-static-import "$adapter"; then
    rm -rf "$HOME/.cache/tmp/jiti"
fi

step "Installing the SkillSpector extensions"
for file in /usr/local/share/skillspector/opencode/commands/skillspector.md /usr/local/share/skillspector/opencode/plugins/skillspector.js; do
    target="$HOME/.config/opencode/${file#/usr/local/share/skillspector/opencode/}"
    if [ ! -e "$target" ]; then
        install -Dm644 "$file" "$target"
    fi
done
if [ ! -e "$HOME/.pi/agent/extensions/skillspector.js" ]; then
    install -Dm644 /usr/local/share/pi/extensions/skillspector.js \
        "$HOME/.pi/agent/extensions/skillspector.js"
fi

step "Configuring OpenCode service networking"
opencode service set hostname 0.0.0.0

printf '\nInitialization complete.\n'
