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
        "The model never executed anything — it emitted a request and your code obeyed.",
        "`execute_tool()` has no caller identity and no veto. That is the governance gap.",
        "`tool_use_id` is the correlation key any interception layer must preserve.",
        "Next: Lab 2 puts this exchange in a loop, and the loop is where it gets dangerous.",
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
        "LAB 2",
        "The ReAct Loop",
        "Reason -> Act -> Observe, until the model stops asking for tools.",
    )

    async with Client(stdio_client(server_params())) as client:
        tool_list = await client.list_tools()
        tool_names = [tool.name for tool in tool_list.tools]
        c.kv("Model", MODEL)
        c.kv("Client-side cap", f"{MAX_ITERATIONS} iterations  (advisory only!)")
        c.kv("Tools advertised", ", ".join(tool_names))
        print()

        await chat_loop(client)


if __name__ == "__main__":
    asyncio.run(main())