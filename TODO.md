# TODO

## Default to prototype-scope when no context is given

Observed live via a Codex CLI test run: Codex called `challenge_idea` with `idea` set
to a small utility function but never set `context`, and got 8 straight rejections
from `inquisitor` plus further critique from `chief_architect` (race condition,
streaming vs. full-file load) - some of it valid, some of it enterprise-grade rigor
that likely wasn't warranted for what was actually a quick local test.

Root cause: without `context`, the personas have no scope to check against, so they
fall back to assuming full production/enterprise rigor is required. That's a bias in
the persona prompts, not just a caller mistake - it should be fixed there so it doesn't
depend on every caller remembering to pass `context`.

Two-part fix:

1. **Change the default assumption in `_CONTEXT_CHECK_RULE`** (`personas.py`): when no
   `context` is given, personas should assume a small-scope/local/prototype use case
   rather than defaulting to distributed-systems/enterprise-production rigor. Only
   escalate to that stricter standard when the code or context itself provides
   evidence it's warranted (e.g. explicit concurrency, network exposure, multi-tenant
   data).
2. **Sharpen the `challenge_idea` docstring** (`server.py`) to make clearer that
   omitting `context` triggers this more lenient default - nudging calling agents that
   read the tool description to actually supply it.

Trade-off to keep in mind: this makes genuinely under-engineered code without context
slightly more likely to pass. Acceptable, since the context-check rule still escalates
when the context (or the code itself) signals real risk - this only changes the prior
when nothing is known.
