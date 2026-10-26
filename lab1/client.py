import asyncio
import sys

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_types import TextContent

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env

MODEL = "claude-haiku-4-5-20251001"
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

    # Initial Claude API call
    response = anthropic.messages.create(
        model=MODEL,
        max_tokens=1000,
        messages=messages,
        tools=available_tools
    )

    # Process response and handle tool calls
    final_text = []
    tool_results = []

    for content in response.content:
        if content.type == 'text':
            final_text.append(content.text)
        elif content.type == 'tool_use':
            tool_name = content.name
            tool_args = content.input

            # Execute tool call
            result = await client.call_tool(tool_name, tool_args)
            final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")

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
            max_tokens=1000,
            messages=messages,
            tools=available_tools
        )

        for content in response.content:
            if content.type == 'text':
                final_text.append(content.text)

    return "\n".join(final_text)

async def chat_loop(client: Client) -> None:
    """Run an interactive chat loop"""
    print("\nMCP Client Started!")
    print("Type your queries or 'quit' to exit.")

    while True:
        try:
            query = (await asyncio.to_thread(input, "\nQuery: ")).strip()
        except EOFError:
            break

        if query.lower() == 'quit':
            break

        if not query:
            query = "What is the weather in quebec today ?"
            print(f"Query is: {query}")

        try:
            response = await process_query(client, query)
            print("\n" + response)
        except Exception as e:
            print(f"\nError: {e}")

async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)

    async with Client(stdio_client(server_params(sys.argv[1]))) as client:
        tool_list = await client.list_tools()
        tool_names = [tool.name for tool in tool_list.tools]
        print("\nConnected to server with tools:", tool_names)

        await chat_loop(client)


if __name__ == "__main__":
    asyncio.run(main())