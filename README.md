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
review. Built as a "devil's advocate" for Claude: instead of presenting proposals
unchallenged, Claude has an independent second model interrogate them first.

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
`KONTRA_KI_LM_STUDIO_URL` to override it (see below).

### 2. Install Kontra-KI

```bash
cd /path/to/kontra-ki
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Register as an MCP server (Claude Code)

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
claude mcp add kontra-ki --scope user --env KONTRA_KI_LM_STUDIO_URL=http://<host>:<port> -- /path/to/kontra-ki/.venv/bin/python -m kontra_ki.server
```

`--scope user` makes the server available in every new session, regardless of working
directory. It then shows up as the `challenge_idea` tool.

## Tool

`challenge_idea(idea: str, context: str = "", persona: str = "diabolo", strict: bool = False) -> str`

Sends `idea` (plus optional `context`) to LM Studio with the chosen persona's system
prompt and returns the local model's critique. System prompts are deliberately in
English (better instruction-following on smaller local models), but the model replies
in whatever language the input was written in.

### Strict mode

Only for `inquisitor` and `code_skeptic` (the two personas with genuine pass/fail
semantics): with `strict=True`, the persona also issues a verdict (`VERDICT: REJECT` /
`VERDICT: PASS`). On `REJECT`, the tool call itself comes back as an MCP tool error
(`isError=True`, via `ToolError`) instead of plain text - the calling model gets the
"must fix this" reflex instead of a skimmable text comment. If the local model doesn't
emit the expected verdict format, the tool fails open (text is returned normally, no
silent failure). Requesting `strict=True` on a persona that doesn't support it returns
a clear error instead of being silently ignored.

### Personas

| Key | Role |
|---|---|
| `diabolo` (default) | Devil's advocate - methodically dismantles arguments/code/ideas, never agrees |
| `cynic` | Jaded senior developer - focuses on scale, "where does this break", overengineering |
| `antithesis` | Radically takes the opposite position to whatever the user argues |
| `code_skeptic` | Paranoid code auditor - maintainability, tests, abstractions, no solutions offered |
| `inquisitor` | Code inquisitor - rejects pseudocode, TODOs, omissions; demands 100% production-readiness |
| `chief_architect` | Impatient chief architect - no platitudes, demands Big-O/protocols/race-condition proof |
| `sycophant_hunter` | Audits the *response itself*, not code/arguments - flags praise, softened risk, or hedging shaped to please the asker rather than be correct |

To add a persona: add an entry to the `PERSONAS` dict in `kontra_ki/personas.py`, and a
matching one to `PROMPT_DESCRIPTIONS` in `kontra_ki/prompts.py` (the two are asserted to
stay in sync at import time).

### Prompts

Each persona is also registered as an MCP prompt (`diabolo`, `cynic`, `antithesis`,
`code_skeptic`, `inquisitor`, `chief_architect`, `sycophant_hunter`), so clients that show
a prompt picker (e.g. Claude Desktop) can select a persona directly instead of only
reaching it through the `persona` string argument of `challenge_idea`. Each prompt takes
`idea` (required) and `context` (optional); `code_skeptic` and `inquisitor` additionally
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
- `kontra_ki/server.py` - MCP server, wires the tool call to persona + client, audit logging
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
- **`isError` flag is optional and persona-restricted**: only `inquisitor` and
  `code_skeptic` have genuine pass/fail semantics. The pure discussion personas
  (`diabolo`, `cynic`, `antithesis`, `chief_architect`) have no verdict - their
  critique is opinion, not a ruling; `strict=True` there is rejected with an error
  instead of silently ignored.
