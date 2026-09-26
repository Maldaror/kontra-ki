"""MCP server exposing kontra-ki's adversarial review tool."""

import re

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from kontra_ki.lm_studio_client import LMStudioError, ask
from kontra_ki.personas import (
    DEFAULT_PERSONA,
    PERSONAS,
    STRICT_CAPABLE_PERSONAS,
    VERDICT_INSTRUCTION,
)

_VERDICT_RE = re.compile(r'^VERDICT:\s*(REJECT|PASS)\s*$', re.IGNORECASE)

mcp = MCPServer("kontra-ki")


def _split_verdict(reply: str) -> tuple[str, str | None]:
    """Strips a trailing "VERDICT: REJECT/PASS" line and returns (body, verdict).

    verdict is None if the model didn't emit a well-formed verdict line - callers
    must fail open in that case rather than silently swallowing the critique.
    """
    lines = reply.rstrip().splitlines()
    if not lines:
        return reply, None
    match = _VERDICT_RE.match(lines[-1].strip())
    if match is None:
        return reply, None
    return "\n".join(lines[:-1]).rstrip(), match.group(1).upper()


@mcp.tool()
async def challenge_idea(
    idea: str,
    context: str = "",
    persona: str = DEFAULT_PERSONA,
    strict: bool = False,
) -> str:
    """Sends an idea, design, or assumption to an independent local LLM (LM Studio)
    for adversarial review. Use this to have your own proposals challenged before
    presenting them to the user as finished.

    Args:
        idea: The idea, design decision, or assumption to challenge.
        context: Optional background (project, constraints, prior decisions) that
            helps the reviewing model target its critique.
        persona: Which adversarial persona should respond. Options: "diabolo"
            (devil's advocate, methodically dismantles arguments), "cynic" (jaded
            senior developer, focuses on scale/overengineering), "antithesis" (takes
            the radical opposite position), "code_skeptic" (paranoid code auditor,
            focuses on maintainability/tests/abstractions), "inquisitor" (rejects
            incomplete or non-production-ready code outright), "chief_architect"
            (impatient architect, demands hard quantitative proof, zero platitudes).
            Default: "diabolo".
        strict: Only valid for personas with pass/fail semantics ("inquisitor",
            "code_skeptic"). When True, the persona also issues a verdict; on
            reject, this tool call itself comes back as an MCP tool error
            (isError=True) instead of plain text, so the failure can't be skimmed
            past as a casual comment. Default: False.
    """
    if persona not in PERSONAS:
        raise ToolError(f"Unknown persona '{persona}'. Available: {', '.join(PERSONAS)}.")

    if strict and persona not in STRICT_CAPABLE_PERSONAS:
        raise ToolError(
            f"Persona '{persona}' does not support strict mode. "
            f"Strict-capable personas: {', '.join(sorted(STRICT_CAPABLE_PERSONAS))}."
        )

    user_content = f"Context:\n{context}\n\nIdea to challenge:\n{idea}" if context else idea
    system_prompt = PERSONAS[persona] + (VERDICT_INSTRUCTION if strict else "")

    try:
        reply = await ask(system_prompt, user_content)
    except LMStudioError as exc:
        raise ToolError(str(exc)) from exc

    if not strict:
        return reply

    critique, verdict = _split_verdict(reply)
    if verdict == "REJECT":
        raise ToolError(critique)
    return critique


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
