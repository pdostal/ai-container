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
 * markers and show a random emoji from BUSY_EMOJIS at the start of the footer
 * stats line while the model is reasoning. The reasoning itself remains
 * available via Ctrl+T.
 *
 * Running tools: keep that same emoji indicator up while a tool call executes,
 * re-rolling it every BUSY_TICK_MS, so long-running commands are visible
 * without scrolling the transcript.
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
// Shown while the agent is busy (reasoning or running a tool), re-rolled on
// every tick. Only TOOL_STATUS is ever set: the footer patch below joins the
// inline keys with a space, so filling both would render two emojis.
const BUSY_EMOJIS = ["🧠", "🍺", "🍕", "🚆", "🛠️", "🔨", "🐣", "🚗", "🚀"];
const BUSY_TICK_MS = 900;

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
    let ticker;
    let emoji;

    const isBusy = () => thinking || activeTools.size > 0;

    const rollEmoji = () => {
        if (BUSY_EMOJIS.length < 2) {
            return BUSY_EMOJIS[0];
        }
        let next;
        do {
            next = BUSY_EMOJIS[Math.floor(Math.random() * BUSY_EMOJIS.length)];
        } while (next === emoji);
        return next;
    };

    const stopTicker = () => {
        if (ticker !== undefined) {
            clearInterval(ticker);
            ticker = undefined;
        }
    };

    const startTicker = (ctx) => {
        if (ticker !== undefined) {
            return;
        }
        ticker = setInterval(() => {
            if (!isBusy()) {
                stopTicker();
                return;
            }
            emoji = rollEmoji();
            try {
                ctx.ui.setStatus(TOOL_STATUS, emoji);
            } catch {
                // The UI can be torn down mid-shutdown; drop the timer instead
                // of throwing from inside a callback.
                stopTicker();
            }
        }, BUSY_TICK_MS);
    };

    // Recompute the indicator after a state change. Only transitions act:
    // re-rolling on every message_update would flicker mid-reasoning.
    const syncBusy = (ctx) => {
        if (ctx) {
            toolContext = ctx;
        }
        const target = ctx ?? toolContext;
        if (!target?.ui) {
            return;
        }
        if (isBusy()) {
            emoji = rollEmoji();
            target.ui.setStatus(TOOL_STATUS, emoji);
            startTicker(target);
        } else {
            stopTicker();
            emoji = undefined;
            toolContext = undefined;
            target.ui.setStatus(TOOL_STATUS, undefined);
        }
    };

    const setThinking = (ctx, next) => {
        if (next === thinking) {
            return;
        }
        thinking = next;
        syncBusy(ctx);
    };

    const updateToolStatus = (ctx) => {
        syncBusy(ctx);
    };

    const clearToolStatus = (ctx) => {
        activeTools.clear();
        thinking = false;
        const target = ctx ?? toolContext;
        toolContext = undefined;
        stopTicker();
        emoji = undefined;
        target?.ui?.setStatus(TOOL_STATUS, undefined);
        target?.ui?.setStatus(THINKING_STATUS, undefined);
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
