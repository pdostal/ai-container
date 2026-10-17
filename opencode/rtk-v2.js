import { execFile } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(execFile);

export default {
  id: "rtk",
  async setup(ctx) {
    await ctx.tool.hook("execute.before", async (event) => {
      if (event.tool !== "shell") return;
      const input = event.input;
      if (typeof input?.command !== "string") return;
      try {
        const { stdout } = await run("rtk", ["rewrite", input.command]);
        if (stdout.trim()) input.command = stdout.trim();
      } catch {
        // Leave commands unchanged when RTK is unavailable.
      }
    });
  },
};
