import { createRequire } from "node:module";
import { existsSync, readFileSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const directory = join(process.env.XDG_CONFIG_HOME || join(process.env.HOME, ".config"), "opencode");
const plugin = join(directory, "plugins", "caveman");
const flag = join(directory, ".caveman-active");

// Caveman's helpers are CommonJS files loaded by the OpenCode binary.
function load(name) {
  const file = join(plugin, name);
  if (!existsSync(file)) return null;
  const module = { exports: {} };
  const source = readFileSync(file, "utf8").replace(/^#![^\n]*\n/, "");
  new Function("module", "exports", "require", "__dirname", "__filename", source)(
    module, module.exports, createRequire(pathToFileURL(file).href), plugin, file,
  );
  return module.exports;
}

export default {
  id: "caveman",
  async setup(ctx) {
    const config = load("caveman-config.cjs");
    const parse = load("caveman-parse.cjs");
    if (!config || !parse) return;

    const set = (mode) => {
      config.recordModeChange?.(directory, mode);
      if (mode) config.safeWriteFlag(flag, mode);
      else try { unlinkSync(flag); } catch (error) { if (error.code !== "ENOENT") throw error; }
    };
    const start = () => {
      const mode = config.getDefaultMode();
      set(mode === "off" ? null : mode === "manual" ? "caveman" : mode);
    };
    start();

    await ctx.session.hook("prompt", (event) => {
      const change = parse.parseModeChange(event.prompt.text, {
        getDefaultMode: config.getDefaultMode, expandedTpl: true, unwrapQuotes: true,
      });
      if (change?.action === "status") {
        event.prompt.text = `Report this status verbatim without changing mode: Caveman mode: ${config.readFlag(flag) || "off"}`;
        return;
      }
      const active = config.readFlag(flag);
      if (change?.action === "set") {
        if (parse.INDEPENDENT_MODES.has(change.mode)) {
          if (active && !parse.INDEPENDENT_MODES.has(active)) config.writeSessionPrev?.(directory, null, active);
          else if (!active) config.writeSessionPrev?.(directory, null, "off");
        } else config.clearSessionPrev?.(directory, null);
        set(change.mode);
      } else if (change?.action === "clear") {
        config.clearSessionPrev?.(directory, null);
        set(null);
      } else if (active && parse.INDEPENDENT_MODES.has(active) && config.readSessionPrev) {
        const previous = config.readSessionPrev(directory, null);
        config.clearSessionPrev(directory, null);
        set(previous && previous !== "off" ? previous : null);
      }
    });

    const reinforce = (event) => {
      const mode = config.readFlag(flag);
      if (!mode || parse.INDEPENDENT_MODES.has(mode)) return;
      const rules = [plugin, directory].map((base) => config.loadRuleset?.(mode, base)).find(Boolean)?.trimEnd();
      event.system.push({ type: "text", text: `CAVEMAN MODE ACTIVE (${mode}) — session ruleset applies.${rules ? `\n\n${rules}` : ""}` });
    };
    await ctx.session.hook("context", reinforce);
    await ctx.session.hook("compaction", reinforce);

    const controller = new AbortController();
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          if (event.type === "session.created") start();
        }
      } catch (error) {
        if (!controller.signal.aborted) console.error("caveman event subscription failed", error);
      }
    })();
    return () => controller.abort();
  },
};
