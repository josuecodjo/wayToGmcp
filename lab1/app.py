"""Lab 1 — Native Tool Calling
=============================

WHAT THIS LAB BUILDS
    The smallest possible complete tool call: one Python function, one JSON
    Schema describing it, and two round-trips to Claude. No MCP, no proxy, no
    policy. This is the baseline you must understand before you can govern it.

THE MECHANIC YOU ARE LEARNING
    An LLM cannot execute anything. What it can do is emit a structured
    request — a `tool_use` content block — that names a tool and supplies
    arguments matching the schema you advertised. *Your code* executes. Then
    you hand the output back as a `tool_result` block and ask the model again.

    That gap between "the model asked" and "your code ran" is the single most
    important fact in this entire repository. It is a seam. Everything the
    Control Plane does — identity checks, policy evaluation, budget debits,
    audit logging — happens inside that seam.

WHAT THIS EXPOSES (the gap Lab 5+ closes)
    Look at `execute_tool()` below. It executes whatever the model asked for,
    with no notion of *who* is asking or *whether they may*. That is the
    default posture of every agent framework in production today.

RUN
    source secrets.sh && python3 lab1/app.py
"""

from __future__ import annotations

import json
import sys
import pathlib

# Labs import the shared console from the repo root. Two lines of explicit
# path setup beats a packaging step for a teaching repo.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from anthropic import Anthropic

from labkit import console as c

# Haiku is used across labs 1-9 because these runs are executed repeatedly and
# the reasoning demanded of the model is shallow. Swap to "claude-opus-5" if
# you want to see stronger planning in Lab 2's multi-hop chain.
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024


# --------------------------------------------------------------------------
# 1. THE CAPABILITY
#    A plain Python function. Nothing about it knows it will be called by a
#    language model. In Lab 3 this is replaced by a real MCP server process;
#    the agent-side code barely changes, which is the point of MCP.
# --------------------------------------------------------------------------

def get_weather(location: str) -> str:
    """Return canned weather for a city. Stands in for a real HTTP API."""
    mock_db = {
        "San Francisco": "65F and foggy",
        "Quebec": "50F and clear",
    }
    return mock_db.get(location, "Weather data not available")


# --------------------------------------------------------------------------
# 2. THE TOOL DESCRIPTOR
#    This dict is the model's entire view of the capability. It is also the
#    object the gMCP specification (Q3 2027) extends: risk tier, cost per
#    call, data classes, and allowed identities all get attached here.
#    Compare this with spec/registry/sqlite.gmcp.json once you reach Lab 5.
# --------------------------------------------------------------------------

WEATHER_TOOL = {
    "name": "get_weather",
    "description": "Get the current weather for a specific city.",
    "input_schema": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "The city name, e.g., 'Quebec'",
            }
        },
        "required": ["location"],
        "additionalProperties": False,
    },
}

# Name -> callable. In Lab 2 this dispatch table grows; by Lab 3 it disappears
# entirely, because dispatch becomes the MCP server's job.
DISPATCH = {"get_weather": get_weather}


def execute_tool(name: str, args: dict) -> str:
    """Run a tool the model requested.

    NOTE THE ABSENT ARGUMENTS. There is no caller identity, no policy handle,
    no budget ledger. Lab 5 adds the first, Lab 6 the third — and both do it
    *outside* this process, in a proxy, so that a compromised or careless
    client cannot simply skip the check.
    """
    return DISPATCH[name](**args)


def main() -> int:
    c.banner(
        "LAB 1",
        "Native Tool Calling",
        "One capability, one schema, two model turns — the ungoverned baseline.",
    )

    # Anthropic() resolves ANTHROPIC_API_KEY from the environment itself.
    # Passing os.environ.get(...) explicitly only turns a missing key into a
    # more confusing error, so let the SDK do it.
    client = Anthropic()

    question = "What is the weather like in Quebec today?"
    messages = [{"role": "user", "content": question}]

    c.kv("Model", MODEL)
    c.kv("Tools advertised", ", ".join(t["name"] for t in [WEATHER_TOOL]))
    print()
    c.user(question)

    # ---- TURN 1 ---------------------------------------------------------
    # The model sees the question and the tool schema, and decides whether a
    # tool is needed. It answers with `stop_reason == "tool_use"` and one or
    # more tool_use blocks.
    c.section("Turn 1 — model inspects the question and requests a tool")

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=[WEATHER_TOOL],
        messages=messages,
    )

    # The conversation is stateless on Anthropic's side: you resend the whole
    # history every turn. Append the raw content blocks, not just the text —
    # the tool_use blocks must survive verbatim or the tool_result below will
    # have nothing to attach to.
    messages.append({"role": "assistant", "content": response.content})

    c.kv("stop_reason", response.stop_reason)
    tool_uses = [b for b in response.content if b.type == "tool_use"]

    if not tool_uses:
        c.warn("Model answered without calling a tool — nothing to govern here.")
        text = " ".join(b.text for b in response.content if b.type == "text")
        c.agent(text)
        return 0

    # ---- EXECUTION ------------------------------------------------------
    # This is the seam. Everything the Control Plane will ever do happens
    # between the line above and the line below.
    c.section("Execution — your code runs, the model does not")

    tool_results = []
    for tu in tool_uses:
        c.tool_call(tu.name, tu.input)

        try:
            result = execute_tool(tu.name, tu.input)
            is_error = False
        except Exception as exc:  # noqa: BLE001 — surface any failure to the model
            result, is_error = f"{type(exc).__name__}: {exc}", True

        c.tool_result(result, is_error=is_error)

        # `tool_use_id` stitches the result back to the request. Lose it, or
        # reorder it, and the API rejects the turn. A proxy sitting in this
        # path (Lab 4) must preserve these IDs byte-for-byte.
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": tu.id,
            "content": json.dumps({"result": result}),
            "is_error": is_error,
        })

    # Tool results go back in a *user* turn. All results for one assistant
    # turn must travel in a single message.
    messages.append({"role": "user", "content": tool_results})

    # ---- TURN 2 ---------------------------------------------------------
    c.section("Turn 2 — model reads the observation and answers")

    final = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=[WEATHER_TOOL],
        messages=messages,
    )
    c.agent(" ".join(b.text for b in final.content if b.type == "text"))

    c.takeaway([
        "The model never executed anything — it emitted a request and your code obeyed.",
        "`execute_tool()` has no caller identity and no veto. That is the governance gap.",
        "`tool_use_id` is the correlation key any interception layer must preserve.",
        "Next: Lab 2 puts this exchange in a loop, and the loop is where it gets dangerous.",
    ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
