import pytest
from mcp.server.mcpserver.exceptions import ToolError

from kontra_ki import server
from kontra_ki.lm_studio_client import LMStudioError
from kontra_ki.server import _split_verdict, challenge_idea


class TestSplitVerdict:
    def test_no_verdict_line(self):
        body, verdict = _split_verdict("just a critique\nwith two lines")
        assert body == "just a critique\nwith two lines"
        assert verdict is None

    def test_reject(self):
        body, verdict = _split_verdict("critique text\nVERDICT: REJECT")
        assert body == "critique text"
        assert verdict == "REJECT"

    def test_pass(self):
        body, verdict = _split_verdict("critique text\nVERDICT: PASS")
        assert body == "critique text"
        assert verdict == "PASS"

    def test_case_insensitive(self):
        body, verdict = _split_verdict("critique text\nverdict: reject")
        assert body == "critique text"
        assert verdict == "REJECT"

    def test_empty_reply(self):
        body, verdict = _split_verdict("")
        assert body == ""
        assert verdict is None

    def test_markdown_wrapped_verdict_fails_open(self):
        # Documents current behavior: a verdict line wrapped in formatting
        # (e.g. "**VERDICT: REJECT**") does not match and is treated as
        # regular critique text rather than silently swallowed.
        body, verdict = _split_verdict("critique text\n**VERDICT: REJECT**")
        assert body == "critique text\n**VERDICT: REJECT**"
        assert verdict is None


class TestChallengeIdea:
    async def test_unknown_persona_raises_tool_error(self):
        with pytest.raises(ToolError, match="Unknown persona"):
            await challenge_idea(idea="test", persona="does_not_exist")

    async def test_strict_on_unsupported_persona_raises_tool_error(self):
        with pytest.raises(ToolError, match="does not support strict mode"):
            await challenge_idea(idea="test", persona="diabolo", strict=True)

    async def test_lm_studio_error_raises_tool_error(self, monkeypatch):
        async def fake_ask(system_prompt, user_content):
            raise LMStudioError("LM Studio is not reachable")

        monkeypatch.setattr(server, "ask", fake_ask)

        with pytest.raises(ToolError, match="not reachable"):
            await challenge_idea(idea="test")

    async def test_non_strict_returns_reply_verbatim(self, monkeypatch):
        async def fake_ask(system_prompt, user_content):
            return "here is my critique"

        monkeypatch.setattr(server, "ask", fake_ask)

        result = await challenge_idea(idea="test", persona="cynic")
        assert result == "here is my critique"

    async def test_strict_reject_raises_tool_error_with_critique_body(self, monkeypatch):
        async def fake_ask(system_prompt, user_content):
            return "this is broken\nVERDICT: REJECT"

        monkeypatch.setattr(server, "ask", fake_ask)

        with pytest.raises(ToolError, match="this is broken"):
            await challenge_idea(idea="test", persona="code_skeptic", strict=True)

    async def test_strict_pass_returns_critique_without_verdict_line(self, monkeypatch):
        async def fake_ask(system_prompt, user_content):
            return "looks fine\nVERDICT: PASS"

        monkeypatch.setattr(server, "ask", fake_ask)

        result = await challenge_idea(idea="test", persona="inquisitor", strict=True)
        assert result == "looks fine"

    async def test_context_is_prepended_to_user_content(self, monkeypatch):
        captured = {}

        async def fake_ask(system_prompt, user_content):
            captured["user_content"] = user_content
            return "ok"

        monkeypatch.setattr(server, "ask", fake_ask)

        await challenge_idea(idea="the idea", context="the context")
        assert "the context" in captured["user_content"]
        assert "the idea" in captured["user_content"]
