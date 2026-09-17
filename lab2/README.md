# Lab 2 — The ReAct Loop

> **Runs in:** ~15s · **Needs:** `ANTHROPIC_API_KEY` · **Cost:** ~1 cent

## The question this lab answers

*What changes when the agent gets to decide what to do next?*

## What you build

Lab 1's single exchange, wrapped in a loop, with two tools that must be
chained. The question — *"what's the weather at Apple's headquarters?"* — is
chosen so neither tool alone is enough.

```
iteration 1   get_company_hq("Apple")  ──►  "Cupertino"
iteration 2   get_weather("Cupertino") ──►  "75F and sunny"
iteration 3   no tool requested        ──►  final answer, loop exits
```

## Run it

```bash
source secrets.sh
make lab2
```

Expected: three iterations, the second using the first's output.

## The mechanic

**ReAct = Reason → Act → Observe, repeated.** The exit condition is the
*absence* of a tool request: plain text with no `tool_use` block means the
model believes it is done.

Sit with that for a moment. **The termination of your program is a decision
made by a probabilistic system that an attacker may be able to influence.**

## What this exposes

Two failure modes appear here that did not exist in Lab 1.

### 1. The runaway loop

A confused model can call the same tool forever. `MAX_ITERATIONS` is the naive
fix — and look where it lives:

```python
MAX_ITERATIONS = 5      # in the client. In a file the caller controls.
```

A client is not a trust boundary. Anyone running an agent against your tools
can delete that constant, and there is nothing you can do about it.

> **Lab 6 rebuilds this as a Redis token bucket keyed to a verified identity,
> enforced in the proxy.** Deleting the constant then changes nothing.

### 2. Sequential authorisation

The agent called a harmless tool, then pivoted to a second. Authorising the
*session* once, up front, is therefore meaningless — by iteration 2 the agent
is doing something it was not doing at iteration 1.

> **Every iteration must be re-authorised against the specific tool being
> invoked.** Lab 5 does this, on every single `tools/call`.

Generalise it: the agent's capability requirements are not knowable at session
start, because they depend on data the agent has not read yet.

## Design note: `for`/`else`

```python
for turn in range(1, MAX_ITERATIONS + 1):
    ...
    if not tool_requests:
        break
else:
    c.warn("hit the cap with no final answer")
```

Python's `for`/`else` runs the `else` branch only when the loop finishes
*without* `break` — exactly the runaway case, and clearer than a sentinel flag.

## Exercises

1. Set `MAX_ITERATIONS = 1`. The loop exits mid-plan; note that the agent
   produces no answer at all rather than a partial one.
2. Give `get_weather` a city that is not in its dict and watch the agent
   re-plan around the failure.
3. Add a tool that always fails. How many times does the model retry before
   giving up? That number is your real iteration budget, and you did not choose
   it.

---

**Next:** [Lab 3 — Vanilla MCP](../lab3/) replaces these hardcoded functions
with a real server over the wire.
