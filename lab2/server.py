from typing import Any

from mcp.server import MCPServer

# Initialize MCPServer
mcp = MCPServer()

# --------------------------------------------------------------------------
# 1. TWO CAPABILITIES THAT MUST BE CHAINED
#    get_weather only accepts a city. The question asks about a *company*.
#    The model has to discover the city first. This forces a multi-hop plan
#    rather than a single lucky call.
# --------------------------------------------------------------------------
@mcp.tool()
async def get_company_hq(company: str) -> str:
    """Look up a company's headquarters city."""
    hqs = {
        "Apple": "Cupertino",
        "Microsoft": "Redmond",
        "Google": "Mountain View"
    }
    return hqs.get(company, "Unknown location")

@mcp.tool()
async def get_weather(location: str) -> str:
    """Look up current weather for a city."""
    weather = {
        "Cupertino": "75F and sunny",
        "Redmond": "50F and raining"
    }
    return weather.get(location, "Weather unknown")


# --------------------------------------------------------------------------
# 2. THE TOOL DESCRIPTOR
#    This dict is the model's entire view of the capability. It is also the
#    object the gMCP specification extends: risk tier, cost per
#    call, data classes, and allowed identities all get attached here.
#    Compare this with spec/registry/sqlite.gmcp.json once you reach Lab 5.
# --------------------------------------------------------------------------

TOOL_LIST = [
{
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
    }
},
{
    "name": "get_company_hq",
    "description": "Get the city for a specific company.",
    "input_schema": {
        "type": "object",
        "properties": {
            "company": {
                "type": "string",
                "description": "The company name, e.g., 'Apple'",
            }
        },
        "required": ["company"],
        "additionalProperties": False,
    }
}
]

if __name__ == "__main__":
    mcp.run(transport="stdio")