from kontra_ki.personas import PERSONAS, STRICT_CAPABLE_PERSONAS
from kontra_ki.prompts import PROMPT_DESCRIPTIONS
from kontra_ki.server import mcp


class TestPromptRegistration:
    async def test_one_prompt_per_persona(self):
        prompts = await mcp.list_prompts()
        assert {p.name for p in prompts} == set(PERSONAS)

    async def test_descriptions_cover_every_persona(self):
        assert set(PROMPT_DESCRIPTIONS) == set(PERSONAS)

    async def test_only_strict_capable_personas_expose_strict_argument(self):
        prompts = {p.name: p for p in await mcp.list_prompts()}
        for name, prompt in prompts.items():
            arg_names = {a.name for a in (prompt.arguments or [])}
            if name in STRICT_CAPABLE_PERSONAS:
                assert "strict" in arg_names
            else:
                assert "strict" not in arg_names

    async def test_idea_required_context_optional(self):
        prompts = {p.name: p for p in await mcp.list_prompts()}
        for prompt in prompts.values():
            args = {a.name: a.required for a in (prompt.arguments or [])}
            assert args["idea"] is True
            assert args["context"] is False


class TestPromptRendering:
    async def test_renders_persona_and_idea_into_instruction(self):
        result = await mcp.get_prompt("diabolo", {"idea": "the idea"})
        text = result.messages[0].content.text
        assert 'persona="diabolo"' in text
        assert "the idea" in text
        assert "strict=True" not in text

    async def test_renders_context_when_given(self):
        result = await mcp.get_prompt("cynic", {"idea": "the idea", "context": "the context"})
        text = result.messages[0].content.text
        assert "the idea" in text
        assert "the context" in text

    async def test_omits_context_section_when_not_given(self):
        result = await mcp.get_prompt("cynic", {"idea": "the idea"})
        text = result.messages[0].content.text
        assert "Context:" not in text

    async def test_strict_true_is_reflected_in_instruction(self):
        result = await mcp.get_prompt("code_skeptic", {"idea": "the idea", "strict": True})
        text = result.messages[0].content.text
        assert "strict=True" in text
