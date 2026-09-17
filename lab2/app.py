"""Lab 2 — The ReAct Loop
========================

WHAT THIS LAB BUILDS
    Lab 1's single exchange, wrapped in a loop. The agent now plans, acts,
    observes, and re-plans until it can answer. Two tools are provided, and
    the question is deliberately chosen so that neither tool alone is enough:
    the model must call the first, read the result, and feed it to the second.

THE MECHANIC YOU ARE LEARNING
    ReAct = Reason -> Act -> Observe, repeated. The loop's exit condition is
    the *absence* of a tool request: when the model returns plain text with no
    `tool_use` block, it has what it needs and the loop ends.

    That exit condition is entirely under the model's control. Sit with that
    for a moment — the termination of your program is a decision made by a
    probabilistic system that an attacker may be able to influence.

WHAT THIS EXPOSES (the gap Lab 6 closes)
    Two failure modes appear here that did not exist in Lab 1:

    1. THE RUNAWAY LOOP. A confused model can call the same tool forever.
       MAX_ITERATIONS below is the naive fix — but it lives in the *client*.
       A client is not a trust boundary. Anyone running an agent against your
       tools can delete that constant, and there is nothing you can do about
       it. Lab 6 moves the limit server-side, into the proxy, as a Redis
       token bucket keyed by agent identity.

    2. SEQUENTIAL AUTHORISATION. The agent calls a harmless tool first, then
       pivots to a second. Authorising the *session* once, up front, is
       therefore useless. Every single iteration must be re-authorised
       against the specific tool being invoked. Lab 5 does this.

RUN
    source secrets.sh && python3 lab2/app.py
"""

from __future__ import annotations

import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from anthropic import Anthropic

from labkit import console as c

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

# The client-side circuit breaker. Note where it lives: in a file the caller
# controls. Lab 6 rebuilds this as a server-side budget the caller cannot edit.
MAX_ITERATIONS = 5


# --------------------------------------------------------------------------
# 1. TWO CAPABILITIES THAT MUST BE CHAINED
#    get_weather only accepts a city. The question asks about a *company*.
#    The model has to discover the city first. This forces a multi-hop plan
#    rather than a single lucky call.
# --------------------------------------------------------------------------

def get_company_hq(company: str) -> str:
    """Look up a company's headquarters city."""
    hqs = {"Apple": "Cupertino", "Microsoft": "Redmond", "Google": "Mountain View"}
    return hqs.get(company, "Unknown location")


def get_weather(location: str) -> str:
    """Look up current weather for a city."""
    weather = {"Cupertino": "75F and sunny", "Redmond": "50F and raining"}
    return weather.get(location, "Weather unknown")


TOOLS = [
    {
        "name": "get_company_hq",
        "description": "Get the headquarters city for a given technology company.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Company name, e.g. 'Apple'"}
            },
            "required": ["company"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_weather",
        "description": "Get the current weather for a specific city.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name, e.g. 'Cupertino'"}
            },
            "required": ["location"],
            "additionalProperties": False,
        },
    },
]

DISPATCH = {"get_company_hq": get_company_hq, "get_weather": get_weather}


def main() -> int:
    c.banner(
        "LAB 2",
        "The ReAct Loop",
        "Reason -> Act -> Observe, until the model stops asking for tools.",
    )

    client = Anthropic()
    question = "What is the weather currently like at Apple's headquarters?"
    messages = [{"role": "user", "content": question}]

    c.kv("Model", MODEL)
    c.kv("Tools advertised", ", ".join(t["name"] for t in TOOLS))
    c.kv("Client-side cap", f"{MAX_ITERATIONS} iterations  (advisory only!)")
    print()
    c.user(question)

    # ---- THE LOOP -------------------------------------------------------
    # A `for` loop rather than `while True` gives us the iteration cap for
    # free, and Python's for/else runs the `else` branch only when the loop
    # is exhausted without `break` — i.e. exactly the runaway case.
    for turn in range(1, MAX_ITERATIONS + 1):
        c.section(f"Iteration {turn}/{MAX_ITERATIONS}")

        # REASON — ask the model what to do next, given everything so far.
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_requests = [b for b in response.content if b.type == "tool_use"]

        # EXIT — no tool requested means the model believes it is done.
        if not tool_requests:
            text = " ".join(b.text for b in response.content if b.type == "text")
            c.agent(text)
            break

        # ACT — execute every requested tool. The model may request several in
        # one turn; they are independent and all results must return together
        # in a single user message.
        tool_results = []
        for tool_call in tool_requests:
            c.tool_call(tool_call.name, tool_call.input)

            # ------------------------------------------------------------------
            # INTERCEPTION POINT
            # A governance proxy replaces this block. Today it asks no
            # questions. From Lab 5 on, reaching this line requires:
            #   - a verified agent identity (JWT / SPIFFE),
            #   - an OPA allow decision for *this* tool,
            #   - sufficient remaining budget.
            # ------------------------------------------------------------------
            try:
                result = DISPATCH[tool_call.name](**tool_call.input)
                is_error = False
            except Exception as exc:  # noqa: BLE001
                result, is_error = f"{type(exc).__name__}: {exc}", True

            # OBSERVE
            c.tool_result(result, is_error=is_error)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": json.dumps({"result": result}),
                "is_error": is_error,
            })

        messages.append({"role": "user", "content": tool_results})
    else:
        # Loop exhausted without the model ever settling on an answer.
        c.warn(f"Agent stopped: hit the {MAX_ITERATIONS}-iteration cap with no final answer.")
        c.note("In production this cap is client-side and therefore unenforceable.")

    c.takeaway([
        "The agent chained two tools: it had to learn 'Cupertino' before it could ask for weather.",
        "Loop termination is the model's decision, not yours — a prompt-injected model may never stop.",
        "MAX_ITERATIONS lives in the client, so it is a suggestion, not a control. Lab 6 fixes this.",
        "Authorising a session once is meaningless when tool choice changes every iteration. Lab 5 fixes this.",
        "Next: Lab 3 replaces these hardcoded functions with a real MCP server over the wire.",
    ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
