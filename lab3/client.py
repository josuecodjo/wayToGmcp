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

RUN
    uv run client.py
"""

from __future__ import annotations

import asyncio
import sys
import pathlib
import json

# Labs import the shared console from the repo root. Two lines of explicit
# path setup beats a packaging step for a teaching repo.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_types import TextContent

from anthropic import Anthropic
from dotenv import load_dotenv

from labkit import console as c

load_dotenv()  # load environment variables from .env

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1000
MAX_ITERATIONS = 5
DB_PATH = pathlib.Path(__file__).parent / "test.db"

anthropic = Anthropic()


def server_params() -> StdioServerParameters:
    """Describe the subprocess that runs an MCP server

    Args:
        mcp_server: mcp server to be used
    """
    return StdioServerParameters(command="uvx", args=["--with", "mcp<2", "mcp-server-sqlite", "--db-path", str(DB_PATH)])

async def process_query(client: Client, query: str) -> str:
    """Process a query using Claude and available tools"""
    messages = [
        {
            "role": "user",
            "content": query
        }
    ]

    tool_list = await client.list_tools()
    available_tools = [{
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema
    } for tool in tool_list.tools]

    for turn in range(1, MAX_ITERATIONS + 1):
        c.section(f"Iteration {turn}/{MAX_ITERATIONS}")

        # REASON — ask the model what to do next, given everything so far.
        response = anthropic.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=messages,
            tools=available_tools
        )

        # Process response and handle tool calls
        final_text = []
        tool_results = []

        tool_requests = [b for b in response.content if b.type == "tool_use"]

        # EXIT — no tool requested means the model believes it is done.
        if not tool_requests:
            text = " ".join(b.text for b in response.content if b.type == "text")
            c.agent(text)
            break

        c.kv("stop_reason", response.stop_reason)
        for content in response.content:
            if content.type == 'text':
                c.warn("Model answered without calling a tool — nothing to govern here.")
                final_text.append(content.text)
                c.agent(final_text)
            elif content.type == 'tool_use':
                tool_name = content.name
                tool_args = content.input

                # ACT — execute every requested tool. The model may request several in
                # one turn; they are independent and all results must return together
                # in a single user message.

                c.section("Execution — your code runs, the model does not")
                c.tool_call(tool_name, tool_args)
                result = await client.call_tool(tool_name, tool_args)

                # mcp-server-sqlite (mcp 1.x) returns plain text blocks only —
                # no structured_content — so read the text, not the dict.
                result_text = "\n".join(
                    block.text
                    for block in result.content
                    if isinstance(block, TextContent)
                )
                c.tool_result(result_text, is_error=result.is_error)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": content.id,
                    "content": result_text,
                    "is_error": result.is_error
                })

        if tool_results:
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            # Get next response from Claude
            response = anthropic.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=messages,
                tools=available_tools
            )

            for content in response.content:
                if content.type == 'text':
                    final_text.append(content.text)

            c.agent(" ".join(final_text))

    else:
        # Loop exhausted without the model ever settling on an answer.
        c.warn(f"Agent stopped: hit the {MAX_ITERATIONS}-iteration cap with no final answer.")
        c.note("In production this cap is client-side and therefore unenforceable.")

    c.takeaway([
        "Tool schemas came off the wire, not out of this file — discovery is dynamic.",
        "Execution happened in another process. This file never touched SQLite.",
        "`tools/list` and `tools/call` are standard JSON-RPC: language-agnostic interception points.",
        "The agent was handed `write_query` with no restrictions. Nothing here could have said no.",
        "Next: Lab 4 slides a Go proxy into the pipe and starts reading every message.",
    ])

async def chat_loop(client: Client) -> None:
    """Run an interactive chat loop"""
    c.user("MCP Client Started!")
    c.user("Type your queries or 'quit' to exit.")

    while True:
        try:
            query = (await asyncio.to_thread(input, "\nQuery: ")).strip()
        except EOFError:
            break

        if query.lower() == 'quit':
            break

        if not query:
            query = "Create a table called 'employees' with an id and name. Then insert John Doe."
            c.user(query)

        try:
            await process_query(client, query)
        except Exception as e:
            print(f"\nError: {e}")

async def main() -> None:
    c.banner(
        "LAB 3",
        "Vanilla MCP",
        "Discover tools from a real MCP server and delegate execution over JSON-RPC.",
    )

    async with Client(stdio_client(server_params())) as client:
        tool_list = await client.list_tools()
        tool_names = [tool.name for tool in tool_list.tools]
        c.kv("Model", MODEL)
        c.kv("Client-side cap", f"{MAX_ITERATIONS} iterations  (advisory only!)")
        c.kv("MCP server", "mcp-server-sqlite (stdio)")
        c.kv("Database", DB_PATH)
        c.kv("Policy layer", c.red("none — this is the ungoverned baseline"))
        c.kv("Tools advertised", ", ".join(tool_names))
        print()

        await chat_loop(client)


if __name__ == "__main__":
    asyncio.run(main())