import asyncio
import json
import re

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from kontra_ki import server
from kontra_ki.lm_studio_client import LMStudioError
from kontra_ki.personas import PERSONAS
from kontra_ki.server import _split_verdict, challenge_idea, quorum_review


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

    def test_docstring_lists_every_persona(self):
        quoted = set(re.findall(r'"(\w+)"', challenge_idea.__doc__))
        missing = set(PERSONAS) - quoted
        assert not missing, f"personas missing from challenge_idea docstring: {missing}"

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


class TestQuorumReview:
    async def test_rejects_when_reject_quorum_is_reached(self, monkeypatch):
        async def fake_ask(system_prompt, user_content):
            return "unsafe\nVERDICT: REJECT"

        monkeypatch.setattr(server, "ask", fake_ask)

        result = await quorum_review(idea="test")

        parsed = json.loads(result)

        assert parsed["outcome"] == "REJECT"
        assert parsed["policy"] == "reject_precedence"
        assert parsed["votes"] == {
            "code_skeptic": "REJECT",
            "inquisitor": "REJECT",
            "security_auditor": "REJECT",
        }
        assert len(parsed["reviews"]) == 3

    async def test_returns_inconclusive_on_split_vote(self, monkeypatch):
        responses = iter(("looks fine\nVERDICT: PASS", "needs work\nVERDICT: REJECT"))

        async def fake_ask(system_prompt, user_content):
            return next(responses)

        monkeypatch.setattr(server, "ask", fake_ask)

        result = await quorum_review(
            idea="test", personas=["code_skeptic", "inquisitor"]
        )

        assert json.loads(result)["outcome"] == "INCONCLUSIVE"

    async def test_rejects_non_strict_persona(self):
        with pytest.raises(ToolError, match="does not support strict mode"):
            await quorum_review(idea="test", personas=["diabolo", "inquisitor"])

    async def test_rejects_invalid_quorum(self):
        with pytest.raises(ToolError, match="between 2 and 3"):
            await quorum_review(idea="test", quorum=4)

        with pytest.raises(ToolError, match="between 2 and 3"):
            await quorum_review(idea="test", quorum=1)

        with pytest.raises(ToolError, match="must be an integer"):
            await quorum_review(idea="test", quorum=2.0)

    async def test_does_not_replace_explicit_empty_personas(self):
        with pytest.raises(ToolError, match="at least two personas"):
            await quorum_review(idea="test", personas=[])

    async def test_names_persona_when_review_fails(self, monkeypatch):
        async def fake_ask(system_prompt, user_content):
            if "Code Inquisitor" in system_prompt:
                raise LMStudioError("model unavailable")
            return "looks fine\nVERDICT: PASS"

        monkeypatch.setattr(server, "ask", fake_ask)

        parsed = json.loads(await quorum_review(idea="test"))

        failed_review = next(
            review for review in parsed["reviews"] if review["persona"] == "inquisitor"
        )
        assert failed_review == {
            "persona": "inquisitor",
            "status": "error",
            "error": "model unavailable",
        }
        assert parsed["counts"]["error"] == 1

    async def test_records_review_timeout_as_inconclusive(self, monkeypatch):
        async def slow_review(idea, context, persona):
            await asyncio.sleep(1)

        monkeypatch.setattr(server, "_strict_review", slow_review)
        monkeypatch.setattr(server, "QUORUM_TIMEOUT_SECONDS", 0.01)

        parsed = json.loads(
            await quorum_review(
                idea="test", personas=["code_skeptic", "inquisitor"]
            )
        )

        assert parsed["outcome"] == "INCONCLUSIVE"
        assert parsed["counts"]["error"] == 2
        assert all(review["error"] == "review timed out after 0.01s" for review in parsed["reviews"])

    async def test_records_malformed_review_result_as_error(self, monkeypatch):
        async def malformed_review(idea, context, persona):
            return "critique", "MAYBE"

        monkeypatch.setattr(server, "_review_with_timeout", malformed_review)

        parsed = json.loads(await quorum_review(idea="test"))

        assert parsed["outcome"] == "INCONCLUSIVE"
        assert parsed["counts"]["error"] == 3
        assert all(
            review["error"] == "review returned an invalid result shape"
            for review in parsed["reviews"]
        )

    async def test_result_contains_structured_reviews(self, monkeypatch):
        async def fake_ask(system_prompt, user_content):
            return "looks fine\nVERDICT: PASS"

        monkeypatch.setattr(server, "ask", fake_ask)

        result = await quorum_review(idea="test")

        parsed = json.loads(result)
        assert set(parsed) == {"outcome", "policy", "counts", "votes", "reviews"}
        assert all(
            set(review) == {"persona", "status", "verdict", "critique"}
            for review in parsed["reviews"]
        )

    async def test_default_reviews_start_with_security_auditor(self, monkeypatch):
        calls = []

        async def fake_ask(system_prompt, user_content):
            if "application security auditor" in system_prompt:
                calls.append("security_auditor")
            elif "paranoid code auditor" in system_prompt:
                calls.append("code_skeptic")
            else:
                calls.append("inquisitor")
            return "looks fine\nVERDICT: PASS"

        monkeypatch.setattr(server, "ask", fake_ask)

        await quorum_review(idea="test")

        assert calls == ["security_auditor", "code_skeptic", "inquisitor"]

    async def test_parallel_mode_reviews_all_personas(self, monkeypatch):
        calls = []

        async def fake_ask(system_prompt, user_content):
            if "application security auditor" in system_prompt:
                calls.append("security_auditor")
            elif "paranoid code auditor" in system_prompt:
                calls.append("code_skeptic")
            else:
                calls.append("inquisitor")
            return "looks fine\nVERDICT: PASS"

        monkeypatch.setattr(server, "ask", fake_ask)

        parsed = json.loads(await quorum_review(idea="test", mode="parallel"))

        assert parsed["outcome"] == "PASS"
        assert set(calls) == {"security_auditor", "code_skeptic", "inquisitor"}

    async def test_rejects_invalid_quorum_mode(self):
        with pytest.raises(ToolError, match="serial.*parallel"):
            await quorum_review(idea="test", mode="burst")


class TestAuditLogging:
    async def test_unknown_persona_is_logged_as_warning(self, caplog):
        with caplog.at_level("WARNING", logger="kontra_ki"):
            with pytest.raises(ToolError):
                await challenge_idea(idea="test", persona="does_not_exist")
        assert "unknown persona" in caplog.text

    async def test_lm_studio_error_is_logged_as_error(self, monkeypatch, caplog):
        async def fake_ask(system_prompt, user_content):
            raise LMStudioError("boom")

        monkeypatch.setattr(server, "ask", fake_ask)

        with caplog.at_level("ERROR", logger="kontra_ki"):
            with pytest.raises(ToolError):
                await challenge_idea(idea="test")
        assert "call failed" in caplog.text
        assert "boom" in caplog.text

    async def test_successful_strict_call_logs_verdict(self, monkeypatch, caplog):
        async def fake_ask(system_prompt, user_content):
            return "looks fine\nVERDICT: PASS"

        monkeypatch.setattr(server, "ask", fake_ask)

        with caplog.at_level("INFO", logger="kontra_ki"):
            await challenge_idea(idea="test", persona="inquisitor", strict=True)
        assert "verdict=PASS" in caplog.text

    async def test_missing_verdict_is_logged_as_warning(self, monkeypatch, caplog):
        async def fake_ask(system_prompt, user_content):
            return "no verdict line here"

        monkeypatch.setattr(server, "ask", fake_ask)

        with caplog.at_level("WARNING", logger="kontra_ki"):
            with pytest.raises(ToolError, match="no valid verdict"):
                await challenge_idea(idea="test", persona="inquisitor", strict=True)
        assert "verdict=missing" in caplog.text
