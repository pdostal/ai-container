/**
 * ai-container TUI tweaks for pi.
 *
 * Spacing: pi renders each user message with one line of vertical padding and
 * puts a Spacer(1) between messages, which adds up to two blank lines per gap.
 * Keep the Spacer separators and remove the user message's own vertical padding
 * so there is one blank line between messages. Also drop the empty widget
 * spacer that pi keeps above the editor when no extension widgets are present,
 * so the last message sits directly above the input box.
 *
 * Thinking: with hidden thinking blocks enabled, pi writes a "Thinking..."
 * marker into the transcript for every completed reasoning run. Remove those
 * markers and show a blue "Thinking..." at the start of the footer stats line
 * only while the model is currently reasoning. The reasoning itself remains
 * available via Ctrl+T.
 *
 * Running tools: show "Working..." at the start of the same footer stats line
 * while a tool call is executing, so long-running commands are visible without
 * scrolling the transcript.
 *
 * The spacing changes are runtime patches because pi 1.5.x has no
 * vertical-spacing setting. They fail closed if pi's internals change.
 */

import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const USER_PATCHED = Symbol.for("ai-container.compact-user-message");
const WIDGETS_PATCHED = Symbol.for("ai-container.compact-widget-spacer");
const FOOTER_PATCHED = Symbol.for("ai-container.compact-footer");
const THINKING_STATUS = "ai-container-thinking";
const TOOL_STATUS = "ai-container-tool";
const INLINE_STATUS_KEYS = [THINKING_STATUS, TOOL_STATUS];

function isThinkingMessage(message) {
    if (message?.role !== "assistant" || !Array.isArray(message.content)) {
        return false;
    }
    const last = message.content.at(-1);
    return last?.type === "thinking" && typeof last.thinking === "string" && last.thinking.length > 0;
}

async function patchTui() {
    const cliPath = process.argv[1];
    if (!cliPath) {
        return;
    }

    let dist;
    try {
        dist = dirname(realpathSync(cliPath));
    } catch {
        return;
    }

    let UserMessageComponent;
    let InteractiveMode;
    let FooterComponent;
    let truncateToWidth = (text) => text;
    try {
        ({ UserMessageComponent } = await import(
            pathToFileURL(join(dist, "modes/interactive/components/user-message.js")).href
        ));
        ({ InteractiveMode } = await import(
            pathToFileURL(join(dist, "modes/interactive/interactive-mode.js")).href
        ));
        ({ FooterComponent } = await import(
            pathToFileURL(join(dist, "modes/interactive/components/footer.js")).href
        ));
    } catch {
        return;
    }

    for (const specifier of [
        "@earendil-works/pi-tui",
        pathToFileURL(join(dist, "node_modules/@earendil-works/pi-tui/dist/index.js")).href,
    ]) {
        try {
            const tui = await import(specifier);
            if (typeof tui.truncateToWidth === "function") {
                truncateToWidth = tui.truncateToWidth;
                break;
            }
        } catch {
            // Try the next location; truncation is only a safety net.
        }
    }

    const userPrototype = UserMessageComponent.prototype;
    if (!userPrototype[USER_PATCHED]) {
        userPrototype[USER_PATCHED] = true;
        const rebuild = userPrototype.rebuild;
        userPrototype.rebuild = function () {
            rebuild.call(this);
            for (const child of this.children) {
                if (typeof child.paddingY === "number") {
                    child.paddingY = 0;
                }
            }
        };
    }

    const modePrototype = InteractiveMode.prototype;
    if (!modePrototype[WIDGETS_PATCHED]) {
        modePrototype[WIDGETS_PATCHED] = true;
        const renderWidgetContainer = modePrototype.renderWidgetContainer;
        modePrototype.renderWidgetContainer = function (container, widgets, _spacerWhenEmpty, leadingSpacer) {
            return renderWidgetContainer.call(this, container, widgets, false, leadingSpacer);
        };
    }

    const footerPrototype = FooterComponent.prototype;
    if (!footerPrototype[FOOTER_PATCHED]) {
        footerPrototype[FOOTER_PATCHED] = true;
        const render = footerPrototype.render;
        footerPrototype.render = function (width) {
            const statuses = this.footerData.getExtensionStatuses();
            const inline = [];
            const removed = [];
            for (const key of INLINE_STATUS_KEYS) {
                const text = statuses.get(key);
                if (text) {
                    inline.push(text);
                    removed.push([key, text]);
                    statuses.delete(key);
                }
            }
            if (inline.length === 0) {
                return render.call(this, width);
            }
            try {
                const lines = render.call(this, width);
                if (lines[1] !== undefined) {
                    lines[1] = truncateToWidth(`${inline.join(" ")} ${lines[1]}`, width, "...");
                }
                return lines;
            } finally {
                for (const [key, text] of removed) {
                    statuses.set(key, text);
                }
            }
        };
    }
}

export default async function (pi) {
    let thinking = false;
    const activeTools = new Set();
    let toolContext;

    const setThinking = (ctx, next) => {
        if (next === thinking) {
            return;
        }
        thinking = next;
        ctx.ui.setStatus(
            THINKING_STATUS,
            next ? ctx.ui.theme.fg("accent", "Thinking...") : undefined,
        );
    };

    const updateToolStatus = (ctx) => {
        toolContext = ctx;
        ctx.ui.setStatus(
            TOOL_STATUS,
            activeTools.size > 0 ? ctx.ui.theme.fg("accent", "Working...") : undefined,
        );
        if (activeTools.size === 0) {
            toolContext = undefined;
        }
    };

    const clearToolStatus = (ctx) => {
        activeTools.clear();
        const target = ctx ?? toolContext;
        toolContext = undefined;
        target?.ui.setStatus(TOOL_STATUS, undefined);
    };

    pi.on("session_start", async (_event, ctx) => {
        ctx.ui.setHiddenThinkingLabel("");
        clearToolStatus(ctx);
        setThinking(ctx, false);
    });

    pi.on("session_shutdown", async (_event, ctx) => {
        clearToolStatus(ctx);
    });

    pi.on("turn_start", async (_event, ctx) => {
        setThinking(ctx, false);
    });

    pi.on("message_end", async (event, ctx) => {
        if (event.message?.role === "assistant") {
            setThinking(ctx, false);
        }
    });

    pi.on("agent_end", async (_event, ctx) => {
        clearToolStatus(ctx);
        setThinking(ctx, false);
    });

    pi.on("message_update", async (event, ctx) => {
        if (event.message?.role !== "assistant") {
            return;
        }
        setThinking(ctx, isThinkingMessage(event.message));
    });

    pi.on("tool_execution_start", async (event, ctx) => {
        if (event.parentToolCallId) {
            return;
        }
        activeTools.add(event.toolCallId);
        updateToolStatus(ctx);
    });

    pi.on("tool_execution_end", async (event, ctx) => {
        if (event.parentToolCallId) {
            return;
        }
        activeTools.delete(event.toolCallId);
        updateToolStatus(ctx);
    });

    await patchTui();
}
