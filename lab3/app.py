"""Lab 3 — Vanilla MCP
=====================


WHAT THIS LAB BUILDS
    Labs 1-2 hardcoded both the tool schemas and the Python functions behind
    them. Here both move out of the process entirely. We launch the official
    open-source `mcp-server-sqlite` as a child process, ask it what tools it
    has, and forward the model's tool calls to it over JSON-RPC.

THE TWO CONCEPTUAL SHIFTS
    1. DYNAMIC DISCOVERY — you no longer write tool schemas. You call
       `tools/list` and translate whatever comes back into Anthropic's
       `input_schema` format. The agent's capabilities are now defined by a
       process you did not write.

    2. DELEGATED EXECUTION — `tools/call` sends the request over a pipe. No
       Python function in this file touches the database.

WHY THIS IS THE PIVOT OF THE WHOLE ROADMAP
    Because MCP standardises the wire format, those two calls — `tools/list`
    and `tools/call` — are the same JSON-RPC methods no matter whether the
    server is written in Python, TypeScript, Go or Rust.

    That is the entire thesis of this project. You do not need to modify the
    model, and you do not need to modify the MCP server. You need a
    man-in-the-middle on the transport that filters `tools/list` responses
    down to what this agent identity may see, and rejects `tools/call`
    requests that violate policy or budget. Lab 4 builds exactly that.

WHAT THIS EXPOSES
    IMPLICIT TRUST. This script assumes `mcp-server-sqlite` is safe and that
    the model will use it sensibly. `write_query` will happily execute
    `DROP TABLE`. There is no policy layer anywhere in this file. Lab 7
    demonstrates how little effort it takes to exploit that.

PREREQUISITES
    - `uv` on PATH (provides `uvx`)
    - ANTHROPIC_API_KEY exported

RUN
    source secrets.sh && python3 lab3/app.py
"""

from __future__ import annotations

import asyncio
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from labkit import console as c

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024
MAX_TURNS = 10

# Resolve the database next to *this file*, not against the shell's working
# directory. The MCP server is a child process and inherits our cwd, so a bare
# "test.db" silently points at a different database depending on where you ran
# the script from.
DB_PATH = pathlib.Path(__file__).parent / "test.db"

TASK = "Create a table called 'employees' with an id and name. Then insert John Doe."


# --------------------------------------------------------------------------
# HOW THE SERVER IS LAUNCHED
#
# `mcp-server-sqlite` 0.1.0 is written against the mcp 1.x low-level Server
# API and crashes on import under mcp 2.x:
#
#     AttributeError: 'Server' object has no attribute 'list_resources'
#
# uvx resolves the server's dependencies independently of our venv, so it
# picks up the latest mcp unless told otherwise. `--with "mcp<2"` pins it.
#
# DEBUGGING NOTE WORTH INTERNALISING: when the server dies at startup, the
# client cannot see why. All it observes is the pipe closing, surfaced as
# `MCPError: Connection closed` out of `session.initialize()`. The real
# traceback is on the server's stderr. An MCP client can only ever report
# transport-level failure — which is precisely why the Lab 4 proxy forwards
# child stderr instead of swallowing it.
# --------------------------------------------------------------------------

SERVER_PARAMS = StdioServerParameters(
    command="uvx",
    args=["--with", "mcp<2", "mcp-server-sqlite", "--db-path", str(DB_PATH)],
)


def to_anthropic_schema(mcp_tool) -> dict:
    """Translate one MCP tool descriptor into an Anthropic tool definition.

    The mapping is 1:1 — which is exactly why a governance layer can sit in
    the middle without either side noticing.

    Field-name gotcha: the mcp 2.x Python SDK exposes snake_case attributes
    (`input_schema`). `inputSchema` is only the JSON-RPC *wire alias*; reading
    it as an attribute raises AttributeError.
    """
    return {
        "name": mcp_tool.name,
        "description": mcp_tool.description,
        "input_schema": mcp_tool.input_schema,
    }


async def main() -> int:
    c.banner(
        "LAB 3",
        "Vanilla MCP",
        "Discover tools from a real MCP server and delegate execution over JSON-RPC.",
    )
    c.kv("Model", MODEL)
    c.kv("MCP server", "mcp-server-sqlite (stdio)")
    c.kv("Database", DB_PATH)
    c.kv("Policy layer", c.red("none — this is the ungoverned baseline"))

    # stdio_client spawns the server and hands back the read/write streams of
    # its stdout/stdin. ClientSession layers the MCP protocol over them.
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:

            # ---- HANDSHAKE ---------------------------------------------
            c.section("initialize — MCP handshake")
            info = await session.initialize()
            c.kv("Server name", info.server_info.name)
            c.kv("Server version", info.server_info.version)

            # ---- DYNAMIC DISCOVERY -------------------------------------
            c.section("tools/list — dynamic discovery")
            mcp_tools = await session.list_tools()
            anthropic_tools = [to_anthropic_schema(t) for t in mcp_tools.tools]

            for t in mcp_tools.tools:
                summary = (t.description or "").splitlines()[0][:58]
                c.kv(f"  {t.name}", c.dim(summary), indent=2)
            c.note(
                f"{len(anthropic_tools)} tools discovered. Nothing here was hardcoded — "
                "and nothing filtered them."
            )

            client = AsyncAnthropic()
            messages = [{"role": "user", "content": TASK}]
            print()
            c.user(TASK)

            # ---- THE REACT LOOP, NOW OVER THE WIRE ---------------------
            for turn in range(1, MAX_TURNS + 1):
                c.section(f"Iteration {turn}/{MAX_TURNS}")

                response = await client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    tools=anthropic_tools,
                    messages=messages,
                )
                messages.append({"role": "assistant", "content": response.content})

                tool_requests = [b for b in response.content if b.type == "tool_use"]
                if not tool_requests:
                    c.agent(" ".join(b.text for b in response.content if b.type == "text"))
                    break

                tool_results = []
                for tool_call in tool_requests:
                    c.tool_call(tool_call.name, tool_call.input)

                    # DELEGATED EXECUTION — one JSON-RPC round trip.
                    # This single line is what the Lab 4 proxy intercepts.
                    mcp_res = await session.call_tool(
                        tool_call.name, arguments=tool_call.input
                    )

                    result_text = "\n".join(
                        b.text for b in mcp_res.content if b.type == "text"
                    )
                    c.tool_result(result_text, is_error=bool(mcp_res.is_error))

                    # A failed tool call is a *successful* JSON-RPC response
                    # carrying is_error=true — the transport worked, the tool
                    # did not. Forward that flag, or the model reads a SQL
                    # error as a normal result and carries on regardless.
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": result_text,
                        "is_error": bool(mcp_res.is_error),
                    })

                messages.append({"role": "user", "content": tool_results})
            else:
                c.warn(f"Hit the {MAX_TURNS}-turn cap without a final answer.")

    c.takeaway([
        "Tool schemas came off the wire, not out of this file — discovery is dynamic.",
        "Execution happened in another process. This file never touched SQLite.",
        "`tools/list` and `tools/call` are standard JSON-RPC: language-agnostic interception points.",
        "The agent was handed `write_query` with no restrictions. Nothing here could have said no.",
        "Next: Lab 4 slides a Go proxy into the pipe and starts reading every message.",
    ])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
