# Kontra-KI

[![Tests](https://github.com/Maldaror/kontra-ki/actions/workflows/test.yml/badge.svg)](https://github.com/Maldaror/kontra-ki/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/kontra-ki-logo-dark.svg">
    <img src="assets/kontra-ki-logo.svg" alt="kontra ki — Ideas, under pressure" width="680">
  </picture>
</p>

MCP server that sends ideas to a locally running LM Studio model for adversarial
review. Built as a "devil's advocate" for coding agents: instead of presenting
proposals unchallenged, the calling agent - Claude Code, Codex CLI, or any other
MCP client - has an independent second model interrogate them first.

## Setup

### 1. LM Studio

1. Load a model (e.g. a local Llama/Qwen/Mistral model).
2. Start the local server in the Developer tab (default: `http://localhost:1234`).

Kontra-KI auto-detects the model: on every call it asks LM Studio's native API
(`/api/v0/models`, not the OpenAI-compatible one - that one doesn't expose load state)
for the single chat-capable model currently loaded, and uses that. No configuration
needed as long as exactly one non-embedding model is loaded. If zero or more than one
are loaded, the call fails with a clear error naming the candidates - set
`KONTRA_KI_MODEL` to disambiguate (see below).

By default Kontra-KI talks to LM Studio at `http://localhost:1234`. If LM Studio runs
elsewhere (a different port, or a different machine on your network), set
`KONTRA_KI_LM_STUDIO_URL` to override it (see below). Remote endpoints must use
HTTPS and require `KONTRA_KI_LM_STUDIO_API_KEY`; local `localhost` usage does not.

Timeouts can be enabled with `KONTRA_KI_TIMEOUT_SECONDS` for chat requests,
`KONTRA_KI_MODEL_LOOKUP_TIMEOUT_SECONDS` (default: `10`) for model discovery, and
`KONTRA_KI_QUORUM_TIMEOUT_SECONDS` for each persona review in a quorum. Chat and
quorum timeouts are unlimited by default; set them explicitly when a calling client
needs a hard upper bound. If an individual quorum review times out or fails,
that failure is included in the structured result and the quorum returns
`INCONCLUSIVE` unless the remaining votes still reach the configured quorum.

### 2. Install Kontra-KI

```bash
cd /path/to/kontra-ki
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Register as an MCP server

Kontra-KI is a standard MCP server over stdio, so it works with any MCP-compatible
client. Two examples:

**Claude Code:**

```bash
claude mcp add kontra-ki --scope user -- /path/to/kontra-ki/.venv/bin/python -m kontra_ki.server
```

To pin a specific model instead of auto-detecting (e.g. if you keep several
chat-capable models loaded at once):

```bash
claude mcp add kontra-ki --scope user --env KONTRA_KI_MODEL=<your-model-name> -- /path/to/kontra-ki/.venv/bin/python -m kontra_ki.server
```

To point at an LM Studio instance that isn't on `localhost:1234`:

```bash
claude mcp add kontra-ki --scope user \
  --env KONTRA_KI_LM_STUDIO_URL=https://<host>:<port> \
  --env KONTRA_KI_LM_STUDIO_API_KEY=<api-key> \
  -- /path/to/kontra-ki/.venv/bin/python -m kontra_ki.server
```

`--scope user` makes the server available in every new session, regardless of working
directory. It then shows up as the `challenge_idea` tool.

**Codex CLI:**

```bash
codex mcp add kontra-ki -- /path/to/kontra-ki/.venv/bin/python -m kontra_ki.server
```

Or add it directly to `~/.codex/config.toml`:

```toml
[mcp_servers.kontra-ki]
command = "/path/to/kontra-ki/.venv/bin/python"
args = ["-m", "kontra_ki.server"]

[mcp_servers.kontra-ki.env]
KONTRA_KI_MODEL = "<your-model-name>"          # optional, see above
KONTRA_KI_LM_STUDIO_URL = "http://<host>:<port>" # optional, see above
```

Any other MCP client follows the same pattern: run
`/path/to/kontra-ki/.venv/bin/python -m kontra_ki.server` over stdio, with the same
two optional environment variables.

## Tool

`challenge_idea(idea: str, context: str = "", persona: str = "diabolo", strict: bool = False) -> str`

Sends `idea` (plus optional `context`) to LM Studio with the chosen persona's system
prompt and returns the local model's critique. System prompts are deliberately in
English (better instruction-following on smaller local models), but the model replies
in whatever language the input was written in.

`quorum_review(idea: str, context: str = "", personas: list[str] | None = None, quorum: int = 2) -> str`

Runs independent strict reviews with the selected strict-capable personas and
aggregates their votes deterministically. It returns JSON with `outcome`, `counts`,
`policy`, `votes`, and the individual `reviews`. The result is `PASS` or `REJECT`
only when the configured quorum is reached; split votes return `INCONCLUSIVE`.
If both vote types reach the quorum, `REJECT` takes precedence and the policy is
reported explicitly as `reject_precedence`. By default, `security_auditor`,
`code_skeptic`, and `inquisitor` vote in that order; a quorum of `2` therefore
requires a majority of the three default voters. Quorums must be at least `2`.
Reviews run sequentially so the
security audit is always the first opinion, followed by the code-quality gates.
Set `KONTRA_KI_QUORUM_MODE=parallel` to run reviews concurrently, or pass
`mode="parallel"` for a single call. The default is `serial`; an explicit call mode
overrides the environment setting.

### Strict mode

Only for `inquisitor`, `code_skeptic`, and `security_auditor` (the personas with genuine pass/fail
semantics): with `strict=True`, the persona also issues a verdict (`VERDICT: REJECT` /
`VERDICT: PASS`). On `REJECT`, the tool call itself comes back as an MCP tool error
(`isError=True`, via `ToolError`) instead of plain text - the calling model gets the
"must fix this" reflex instead of a skimmable text comment. If the local model doesn't
emit the expected verdict format, the tool returns an MCP tool error instead of treating
the review as successful. Requesting `strict=True` on a persona that doesn't support it returns
a clear error instead of being silently ignored.

### Personas

| Key | Role |
|---|---|
| `diabolo` (default) | Devil's advocate - methodically dismantles arguments/code/ideas, never agrees |
| `cynic` | Jaded senior developer - focuses on scale, "where does this break", overengineering |
| `antithesis` | Radically takes the opposite position to whatever the user argues |
| `code_skeptic` | Paranoid code auditor - maintainability, tests, abstractions, no solutions offered |
| `inquisitor` | Code inquisitor - rejects pseudocode, TODOs, omissions; demands 100% production-readiness |
| `security_auditor` | Security auditor - traces concrete vulnerabilities, exploitability, and impact |
| `chief_architect` | Impatient chief architect - no platitudes, demands Big-O/protocols/race-condition proof |
| `sycophant_hunter` | Audits the *response itself*, not code/arguments - flags praise, softened risk, or hedging shaped to please the asker rather than be correct |

To add a persona: add an entry to the `PERSONAS` dict in `kontra_ki/personas.py`, and a
matching one to `PROMPT_DESCRIPTIONS` in `kontra_ki/prompts.py` (the two are asserted to
stay in sync at import time).

### Prompts

Each persona is also registered as an MCP prompt (`diabolo`, `cynic`, `antithesis`,
`code_skeptic`, `inquisitor`, `security_auditor`, `chief_architect`, `sycophant_hunter`), so clients that show
a prompt picker (e.g. Claude Desktop) can select a persona directly instead of only
reaching it through the `persona` string argument of `challenge_idea`. Each prompt takes
`idea` (required) and `context` (optional); `code_skeptic`, `inquisitor`, and
`security_auditor` additionally
take `strict`. A prompt renders to an instruction telling the calling model which
`challenge_idea` call to make - it doesn't call LM Studio itself.

### Chaining personas

The server stays single-shot and stateless on purpose (see Design decisions) - there is
no built-in multi-persona chain tool. Chaining is the calling agent's job: call
`challenge_idea` once, then feed its output back in as the next call's `idea` (with the
original submission as `context`). This composes in either direction:

- **Same target, different angles**: run `inquisitor` and `chief_architect` on the same
  idea independently, then compare verdicts yourself.
- **Critique-of-critique**: run `sycophant_hunter` with a persona's critique as `idea`
  and the original submission as `context`, to check whether that critique itself was
  generic, unearned, or overreaching rather than grounded in the actual input.

### Logging

Every call (accepted, rejected, or failed) is logged to stderr with persona, `strict`,
and - for strict calls - the verdict, so you can audit what was reviewed and when.
Never logged to stdout: that's the stdio transport's JSON-RPC channel, and writing to it
would corrupt the protocol stream. Log level defaults to `INFO`; override with
`KONTRA_KI_LOG_LEVEL` (e.g. `DEBUG`, `WARNING`).

## Structure

- `kontra_ki/personas.py` - persona registry (system prompts, default)
- `kontra_ki/prompts.py` - one MCP prompt template per persona
- `kontra_ki/lm_studio_client.py` - HTTP client for LM Studio's chat completions endpoint
- `kontra_ki/server.py` - MCP server, challenge and quorum tools, audit logging
- `tests/` - pytest suite (verdict parsing, tool error paths, prompt registration/rendering,
  LM Studio client error handling)

## Design decisions

- **Single-shot, no multi-turn state**: every call is independent, no session handling
  needed in the server.
- **Several fixed personas, selectable by parameter**: no freely-composed system
  prompts per call, just a curated set in `personas.py`.
- **LM Studio URL defaults to `http://localhost:1234`**, overridable via
  `KONTRA_KI_LM_STUDIO_URL` for setups where LM Studio runs on a different port or
  host (e.g. another machine on the local network).
- **`isError` flag is optional and persona-restricted**: only `inquisitor`,
  `code_skeptic`, and `security_auditor` have genuine pass/fail semantics. The pure discussion personas
  (`diabolo`, `cynic`, `antithesis`, `chief_architect`) have no verdict - their
  critique is opinion, not a ruling; `strict=True` there is rejected with an error
  instead of silently ignored.
