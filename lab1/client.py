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


RUN
    uv run client.py server.py
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
anthropic = Anthropic()

def server_params(server_script_path: str) -> StdioServerParameters:
    """Describe the subprocess that runs an MCP server

    Args:
        server_script_path: Path to the server script (.py or .js)
    """
    if server_script_path.endswith(".py"):
        command = "python"
    elif server_script_path.endswith(".js"):
        command = "node"
    else:
        raise ValueError("Server script must be a .py or .js file")

    return StdioServerParameters(command=command, args=[server_script_path])

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

    # ---- TURN 1 ---------------------------------------------------------
    # The model sees the question and the tool schema, and decides whether a
    # tool is needed. It answers with `stop_reason == "tool_use"` and one or
    # more tool_use blocks.
    c.section("Turn 1 — model inspects the question and requests a tool")

    # Initial Claude API call
    response = anthropic.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=messages,
        tools=available_tools
    )

    # Process response and handle tool calls
    final_text = []
    tool_results = []

    c.kv("stop_reason", response.stop_reason)
    for content in response.content:
        if content.type == 'text':
            c.warn("Model answered without calling a tool — nothing to govern here.")
            final_text.append(content.text)
            c.agent(final_text)
        elif content.type == 'tool_use':
            tool_name = content.name
            tool_args = content.input

            # ---- EXECUTION ------------------------------------------------------
            # This is the seam. Everything the Control Plane will ever do happens
            # between the line above and the line below.
            c.section("Execution — your code runs, the model does not")

            c.tool_call(tool_name, tool_args)
            result = await client.call_tool(tool_name, tool_args)
            c.tool_result(result.structured_content.get('result'), is_error=result.is_error)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": content.id,
                "content": "\n".join(
                    block.text
                    for block in result.content
                    if isinstance(block, TextContent)
                ),
                "is_error": result.is_error
            })

    if tool_results:
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        # ---- TURN 2 ---------------------------------------------------------
        c.section("Turn 2 — model reads the observation and answers")

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

        c.takeaway([
            "The model never executed anything — it emitted a request and your code obeyed.",
            "`call_tool()` has no caller identity and no veto. That is the governance gap.",
            "`tool_use_id` is the correlation key any interception layer must preserve.",
            "Next: Lab 2 puts this exchange in a loop, and the loop is where it gets dangerous.",
        ])
    return " ".join(final_text)

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
            query = "What is the weather like in Quebec today?"
            c.user(query)

        try:
            await process_query(client, query)
        except Exception as e:
            print(f"\nError: {e}")

async def main() -> None:
    c.banner(
        "LAB 1",
        "Native Tool Calling",
        "One capability, one schema, two model turns — the ungoverned baseline.",
    )

    if len(sys.argv) < 2:
        c.kv("Usage: uv run client.py <path_to_server_script>")
        sys.exit(1)

    async with Client(stdio_client(server_params(sys.argv[1]))) as client:
        tool_list = await client.list_tools()
        tool_names = [tool.name for tool in tool_list.tools]
        c.kv("Model", MODEL)
        c.kv("Tools advertised", ", ".join(tool_names))
        print()

        await chat_loop(client)


if __name__ == "__main__":
    asyncio.run(main())