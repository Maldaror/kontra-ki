"""MCP prompt templates, one per persona.

The personas already live as system prompts in `personas.py` and are reachable
through the `persona` string parameter of the `challenge_idea` tool. Registering
them here as well lets MCP clients (Claude Desktop, etc.) list and pick a
persona directly from their prompt picker, instead of only through a
free-text tool argument.
"""

from kontra_ki.personas import PERSONAS

# Short, client-facing description per persona - shown in the prompt picker.
PROMPT_DESCRIPTIONS: dict[str, str] = {
    "diabolo": "Devil's advocate - methodically dismantles arguments/code/ideas, never agrees.",
    "cynic": 'Jaded senior developer - focuses on scale, "where does this break", overengineering.',
    "antithesis": "Radically takes the opposite position to whatever you argue.",
    "code_skeptic": "Paranoid code auditor - maintainability, tests, abstractions, no solutions offered.",
    "inquisitor": "Code inquisitor - rejects pseudocode, TODOs, omissions; demands 100% production-readiness.",
    "chief_architect": "Impatient chief architect - no platitudes, demands Big-O/protocols/race-condition proof.",
    "sycophant_hunter": (
        "Audits the response itself, not code/arguments - flags praise, softened risk, "
        "or hedging shaped to please the asker rather than be correct."
    ),
}

assert set(PROMPT_DESCRIPTIONS) == set(PERSONAS), (
    "PROMPT_DESCRIPTIONS and PERSONAS have drifted apart - every persona needs a prompt."
)


def _instruction(persona: str, idea: str, context: str, strict: bool = False) -> str:
    instruction = f'Use the challenge_idea tool with persona="{persona}"'
    if strict:
        instruction += " and strict=True"
    instruction += f" to review the following:\n\n{idea}"
    if context:
        instruction += f"\n\nContext:\n{context}"
    return instruction


def register_prompts(mcp) -> None:
    """Registers one MCP prompt per persona on the given server."""

    @mcp.prompt(name="diabolo", description=PROMPT_DESCRIPTIONS["diabolo"])
    def diabolo(idea: str, context: str = "") -> str:
        return _instruction("diabolo", idea, context)

    @mcp.prompt(name="cynic", description=PROMPT_DESCRIPTIONS["cynic"])
    def cynic(idea: str, context: str = "") -> str:
        return _instruction("cynic", idea, context)

    @mcp.prompt(name="antithesis", description=PROMPT_DESCRIPTIONS["antithesis"])
    def antithesis(idea: str, context: str = "") -> str:
        return _instruction("antithesis", idea, context)

    @mcp.prompt(name="code_skeptic", description=PROMPT_DESCRIPTIONS["code_skeptic"])
    def code_skeptic(idea: str, context: str = "", strict: bool = False) -> str:
        return _instruction("code_skeptic", idea, context, strict)

    @mcp.prompt(name="inquisitor", description=PROMPT_DESCRIPTIONS["inquisitor"])
    def inquisitor(idea: str, context: str = "", strict: bool = False) -> str:
        return _instruction("inquisitor", idea, context, strict)

    @mcp.prompt(name="chief_architect", description=PROMPT_DESCRIPTIONS["chief_architect"])
    def chief_architect(idea: str, context: str = "") -> str:
        return _instruction("chief_architect", idea, context)

    @mcp.prompt(name="sycophant_hunter", description=PROMPT_DESCRIPTIONS["sycophant_hunter"])
    def sycophant_hunter(idea: str, context: str = "") -> str:
        return _instruction("sycophant_hunter", idea, context)
