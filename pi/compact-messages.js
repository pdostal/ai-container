/**
 * Tighten the pi transcript spacing.
 *
 * Pi renders each user message with one line of vertical padding and puts a
 * Spacer(1) between messages, which adds up to two blank lines per gap. Keep
 * the Spacer separators and remove the user message's own vertical padding so
 * there is one blank line between messages. Also drop the empty widget spacer
 * that pi keeps above the editor when no extension widgets are present, so the
 * last message sits directly above the input box.
 *
 * This is a runtime patch because pi 1.5.x has no vertical-spacing setting.
 * It fails closed: if pi's internal modules cannot be found, nothing changes.
 */

import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const USER_PATCHED = Symbol.for("ai-container.compact-user-message");
const WIDGETS_PATCHED = Symbol.for("ai-container.compact-widget-spacer");

export default async function () {
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
    try {
        ({ UserMessageComponent } = await import(
            pathToFileURL(join(dist, "modes/interactive/components/user-message.js")).href
        ));
        ({ InteractiveMode } = await import(
            pathToFileURL(join(dist, "modes/interactive/interactive-mode.js")).href
        ));
    } catch {
        return;
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
}
