from typing import Any

from mcp.server import MCPServer

# Initialize MCPServer
mcp = MCPServer()

@mcp.tool()
# --------------------------------------------------------------------------
# 1. THE CAPABILITY
#    A plain Python function. Nothing about it knows it will be called by a
#    language model. In Lab 3 this is replaced by a real MCP server process;
#    the agent-side code barely changes, which is the point of MCP.
# --------------------------------------------------------------------------

async def get_weather(location: str) -> str:
    """Return canned weather for a city. Stands in for a real HTTP API."""
    mock_db = {
        "San Francisco": "65F and foggy",
        "Quebec": "50F and clear",
        "Ottawa" : "10F and cold"
    }
    return mock_db.get(location, "Weather data not available")

# --------------------------------------------------------------------------
# 2. THE TOOL DESCRIPTOR
#    This dict is the model's entire view of the capability. It is also the
#    object the gMCP specification extends: risk tier, cost per
#    call, data classes, and allowed identities all get attached here.
#    Compare this with spec/registry/sqlite.gmcp.json once you reach Lab 5.
# --------------------------------------------------------------------------

TOOL_LIST = {
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

if __name__ == "__main__":
    mcp.run(transport="stdio")