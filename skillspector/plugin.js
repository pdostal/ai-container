import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { resolve } from "node:path";

const run = promisify(execFile);

export default {
  id: "skillspector",
  async setup(ctx) {
    await ctx.tool.transform((editor) => {
      editor.add({
        name: "skillspector_scan",
        description: "Scan an AI agent skill for security risks with SkillSpector (static analysis).",
        input: {
          type: "object",
          properties: { target: { type: "string" } },
          required: ["target"],
          additionalProperties: false,
        },
        async execute(input, context) {
          const target = input.target;
          const remote = /^(https?:\/\/|git@[^:]+:)/.test(target);
          const resource = remote ? target : resolve(ctx.location.directory, target);
          const source = { type: "tool", messageID: context.messageID, id: context.id };
          if (remote) {
            await ctx.permission.assert({ sessionID: context.sessionID, source, action: "webfetch", resources: [resource] });
          } else {
            await ctx.permission.assert({ sessionID: context.sessionID, source, action: "read", resources: [resource] });
          }
          await ctx.permission.assert({ sessionID: context.sessionID, source, action: "shell", resources: ["skillspector scan " + resource + " --no-llm"] });
          try {
            const { stdout, stderr } = await run("skillspector", ["scan", resource, "--no-llm"], {
              cwd: ctx.location.directory, timeout: 120000, maxBuffer: 1024 * 1024, signal: context.signal,
            });
            return { content: (stdout || stderr).slice(0, 12000) };
          } catch (error) {
            if (error.code === 1 && error.stdout) return { content: error.stdout.slice(0, 12000) };
            throw error;
          }
        },
      });
    });
  },
};
