"""MCP server exposing kontra-ki's adversarial review tools."""

import asyncio
import json
import logging
import os
import re
import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from kontra_ki.lm_studio_client import LMStudioError, ask
from kontra_ki.personas import (
    DEFAULT_PERSONA,
    PERSONAS,
    STRICT_CAPABLE_PERSONAS,
    VERDICT_INSTRUCTION,
)
from kontra_ki.prompts import register_prompts

_VERDICT_RE = re.compile(r'^VERDICT:\s*(REJECT|PASS)\s*$', re.IGNORECASE)
_quorum_timeout_value = os.environ.get("KONTRA_KI_QUORUM_TIMEOUT_SECONDS")
QUORUM_TIMEOUT_SECONDS = (
    float(_quorum_timeout_value) if _quorum_timeout_value else None
)

# stdio is the MCP transport's stdout - never log there, or the JSON-RPC
# stream gets corrupted. stderr is the only safe default for this transport.
logger = logging.getLogger("kontra_ki")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(os.environ.get("KONTRA_KI_LOG_LEVEL", "INFO"))
    logger.propagate = False

mcp = MCPServer("kontra-ki")
register_prompts(mcp)


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


def _review_error_message(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        if QUORUM_TIMEOUT_SECONDS is not None:
            return f"review timed out after {QUORUM_TIMEOUT_SECONDS:g}s"
        return "review timed out"
    return str(error) or error.__class__.__name__


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
            helps the reviewing model target its critique. If omitted, personas
            default to assuming a small-scope/local/prototype use case rather than
            production/enterprise rigor - supply context whenever the idea or code
            actually has real scale, concurrency, network exposure, or multi-user
            requirements, or the review won't hold it to that standard.
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
        logger.warning("rejected call: unknown persona=%r", persona)
        raise ToolError(f"Unknown persona '{persona}'. Available: {', '.join(PERSONAS)}.")

    if strict and persona not in STRICT_CAPABLE_PERSONAS:
        logger.warning("rejected call: persona=%s does not support strict mode", persona)
        raise ToolError(
            f"Persona '{persona}' does not support strict mode. "
            f"Strict-capable personas: {', '.join(sorted(STRICT_CAPABLE_PERSONAS))}."
        )

    user_content = f"Context:\n{context}\n\nIdea to challenge:\n{idea}" if context else idea
    system_prompt = PERSONAS[persona] + (VERDICT_INSTRUCTION if strict else "")

    try:
        reply = await ask(system_prompt, user_content)
    except LMStudioError as exc:
        logger.error("call failed: persona=%s strict=%s error=%s", persona, strict, exc)
        raise ToolError(str(exc)) from exc

    if not strict:
        logger.info("call completed: persona=%s strict=False verdict=n/a", persona)
        return reply

    critique, verdict = _split_verdict(reply)
    if verdict is None:
        logger.warning(
            "call failed: persona=%s strict=True verdict=missing", persona
        )
        raise ToolError("Strict review returned no valid verdict.")

    logger.info("call completed: persona=%s strict=True verdict=%s", persona, verdict)
    if verdict == "REJECT":
        raise ToolError(critique)
    return critique


async def _strict_review(
    idea: str, context: str, persona: str
) -> tuple[str, str]:
    if persona not in PERSONAS:
        raise ToolError(f"Unknown persona '{persona}'. Available: {', '.join(PERSONAS)}.")
    if persona not in STRICT_CAPABLE_PERSONAS:
        raise ToolError(
            f"Persona '{persona}' does not support strict mode. "
            f"Strict-capable personas: {', '.join(sorted(STRICT_CAPABLE_PERSONAS))}."
        )

    user_content = f"Context:\n{context}\n\nIdea to challenge:\n{idea}" if context else idea
    try:
        reply = await ask(PERSONAS[persona] + VERDICT_INSTRUCTION, user_content)
    except LMStudioError as exc:
        raise ToolError(str(exc)) from exc

    critique, verdict = _split_verdict(reply)
    if verdict is None:
        raise ToolError("Strict review returned no valid verdict.")
    return critique, verdict


async def _review_with_timeout(
    idea: str, context: str, persona: str
) -> tuple[str, str]:
    review = _strict_review(idea, context, persona)
    if QUORUM_TIMEOUT_SECONDS is None:
        return await review
    return await asyncio.wait_for(review, timeout=QUORUM_TIMEOUT_SECONDS)


@mcp.tool()
async def quorum_review(
    idea: str,
    context: str = "",
    personas: list[str] | None = None,
    quorum: int = 2,
) -> str:
    """Runs independent strict reviews and aggregates their votes deterministically.

    If both vote types reach the configured quorum, REJECT takes precedence.
    """
    selected = sorted(STRICT_CAPABLE_PERSONAS) if personas is None else list(personas)
    if len(selected) < 2:
        raise ToolError("Quorum review requires at least two personas.")
    if len(set(selected)) != len(selected):
        raise ToolError("Quorum review personas must be unique.")
    if quorum < 1 or quorum > len(selected):
        raise ToolError(f"Quorum must be between 1 and {len(selected)}.")
    for persona in selected:
        if persona not in PERSONAS:
            raise ToolError(f"Unknown persona '{persona}'. Available: {', '.join(PERSONAS)}.")
        if persona not in STRICT_CAPABLE_PERSONAS:
            raise ToolError(
                f"Persona '{persona}' does not support strict mode. "
                f"Strict-capable personas: {', '.join(sorted(STRICT_CAPABLE_PERSONAS))}."
            )

    raw_reviews = await asyncio.gather(
        *(_review_with_timeout(idea, context, persona) for persona in selected),
        return_exceptions=True,
    )
    reviews = []
    successful_reviews = []
    for persona, review in zip(selected, raw_reviews):
        if isinstance(review, Exception):
            reviews.append(
                {
                    "persona": persona,
                    "status": "error",
                    "error": _review_error_message(review),
                }
            )
            continue
        critique, verdict = review
        successful_reviews.append((persona, critique, verdict))
        reviews.append(
            {
                "persona": persona,
                "status": "ok",
                "verdict": verdict,
                "critique": critique,
            }
        )
    reject_count = sum(verdict == "REJECT" for _, _, verdict in successful_reviews)
    pass_count = sum(verdict == "PASS" for _, _, verdict in successful_reviews)
    if reject_count >= quorum:
        outcome = "REJECT"
    elif pass_count >= quorum:
        outcome = "PASS"
    else:
        outcome = "INCONCLUSIVE"

    result = {
        "outcome": outcome,
        "policy": "reject_precedence",
        "counts": {
            "pass": pass_count,
            "reject": reject_count,
            "error": len(selected) - len(successful_reviews),
            "quorum": quorum,
        },
        "votes": {persona: verdict for persona, _, verdict in successful_reviews},
        "reviews": reviews,
    }
    return json.dumps(result, ensure_ascii=False)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
