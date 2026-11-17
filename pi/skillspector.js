/**
 * SkillSpector integration for pi.
 *
 * Mirrors the OpenCode extension: a `skillspector_scan` tool for the model and
 * a `/skillspector <path-or-url>` command for the user. The scan is static
 * (`--no-llm`), so it needs no provider credentials and returns quickly.
 */

import { resolve } from "node:path";

const MAX_OUTPUT = 12_000;
const SCAN_TIMEOUT_MS = 120_000;

function isRemote(target) {
    return /^(https?:\/\/|git@[^:]+:)/.test(target);
}

export default function (pi) {
    pi.registerTool({
        name: "skillspector_scan",
        label: "SkillSpector Scan",
        description: "Scan an AI agent skill for security risks with SkillSpector (static analysis).",
        promptSnippet: "Scan a skill path or Git URL with SkillSpector for security risks",
        promptGuidelines: [
            "Use skillspector_scan when the user asks to check an AI agent skill for security risks.",
        ],
        parameters: {
            type: "object",
            properties: {
                target: {
                    type: "string",
                    description: "Skill directory, file, or Git/HTTP URL to scan.",
                },
            },
            required: ["target"],
            additionalProperties: false,
        },
        async execute(_toolCallId, params, signal, onUpdate, ctx) {
            const target = params.target.trim().replace(/^@/, "");
            const resource = isRemote(target) ? target : resolve(ctx.cwd, target);

            onUpdate?.({
                content: [{ type: "text", text: `Scanning ${resource}...` }],
                details: {},
            });

            const result = await pi.exec("skillspector", ["scan", resource, "--no-llm"], {
                cwd: ctx.cwd,
                timeout: SCAN_TIMEOUT_MS,
                maxBuffer: 1024 * 1024,
                signal,
            });
            const output = (result.stdout || result.stderr || "").slice(0, MAX_OUTPUT);

            if (result.code === 0 || (result.code === 1 && result.stdout)) {
                return {
                    content: [{ type: "text", text: output || "SkillSpector returned no output." }],
                    details: {},
                };
            }
            return {
                content: [{ type: "text", text: output || `skillspector exited with code ${result.code}.` }],
                details: {},
                isError: true,
            };
        },
    });

    pi.registerCommand("skillspector", {
        description: "Scan an AI agent skill for security risks with SkillSpector.",
        handler: async (args, ctx) => {
            const target = args.trim();
            if (!target) {
                ctx.ui.notify("Usage: /skillspector <path-or-url>", "warning");
                return;
            }
            const prompt = `Scan the skill at ${target} with the skillspector_scan tool.`;
            if (ctx.isIdle()) {
                pi.sendUserMessage(prompt);
            } else {
                pi.sendUserMessage(prompt, { deliverAs: "followUp" });
                ctx.ui.notify("SkillSpector scan queued", "info");
            }
        },
    });
}
