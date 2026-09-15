# Lab 1 — Native Tool Calling

> **Runs in:** ~10s · **Needs:** `ANTHROPIC_API_KEY` · **Cost:** a fraction of a cent

## The question this lab answers

*What actually happens when an LLM "uses a tool"?*

Everything in this repository — the proxy, the policy engine, the budget
ledger, the CI gate — lives inside the answer. Get this one wrong and the rest
is cargo cult.

## What you build

One Python function, one JSON Schema describing it, two round-trips to Claude.
No MCP, no proxy, no policy. The ungoverned baseline.

```
you ──► Claude ──► "call get_weather(location='Quebec')"
                          │
                     YOUR CODE RUNS IT          ◄── the seam
                          │
you ──► Claude ──► "It's 50F and clear in Quebec."
```

## Run it

```bash
make setup                      # once
cp secrets.example.sh secrets.sh && $EDITOR secrets.sh
source secrets.sh
make lab1
```

Expected: `stop_reason: tool_use`, one `[tool]` line, one `[result]` line, then
a final answer that incorporates the weather.

## The mechanic

**An LLM cannot execute anything.** It emits a structured request — a
`tool_use` content block naming a tool and supplying arguments matching the
schema you advertised. Your code executes. You hand the output back as a
`tool_result` block and ask again.

The gap between *"the model asked"* and *"your code ran"* is the single most
important fact in this repo. It is a seam, and everything the Control Plane
does happens inside it.

Three details that matter later:

| Detail | Why it matters downstream |
|---|---|
| `tool_use_id` correlates request and result | Any proxy in the path (Lab 4) must preserve it byte-for-byte |
| The API is stateless — you resend all history | The proxy is therefore also stateless; session state lives in Redis (Lab 6) |
| Tool schemas are just JSON | Which is why gMCP can extend them without touching MCP (Lab 5, `spec/`) |

## What this exposes

Look at `execute_tool()` in [`app.py`](app.py):

```python
def execute_tool(name: str, args: dict) -> str:
    return DISPATCH[name](**args)
```

**Note the absent arguments.** No caller identity. No policy handle. No budget
ledger. No veto. It executes whatever was asked, on behalf of nobody in
particular.

That is the default posture of most agent deployments running today. Lab 5 adds
identity and policy; Lab 6 adds budget — and both do it *outside this process*,
because a client is not a trust boundary.

## Exercises

1. Ask for a city not in `mock_db`. The tool returns "not available" — watch
   how the model handles a tool that succeeded but was unhelpful. Then make it
   raise instead, and note that `is_error: true` produces different behaviour.
2. Add a second tool and ask a question needing both. The model will request
   them in one turn — you now have parallel tool use, and all results must
   return in a **single** user message.
3. Delete `tool_use_id` from the result block. The API rejects the turn. That
   error is what a careless proxy would cause.

---

**Next:** [Lab 2 — The ReAct Loop](../lab2/) puts this exchange in a loop, and
the loop is where it gets dangerous.
