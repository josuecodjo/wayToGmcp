# Lab 3 — Vanilla MCP

> **Runs in:** ~30s (first run downloads the server) · **Needs:** `uv`, `ANTHROPIC_API_KEY`

## The question this lab answers

*How do we replace hardcoded Python functions with a real MCP server — and why
does that make governance possible?*

## What you build

The agent from Lab 2, but both the tool schemas and the implementations move
out of the process entirely. We launch the official open-source
`mcp-server-sqlite` as a child process and talk JSON-RPC to it over stdio.

```
lab3/app.py  ◄── stdio / JSON-RPC ──►  uvx mcp-server-sqlite  ──►  test.db
  (MCP client)                              (MCP server)
```

## Run it

```bash
source secrets.sh
make lab3
```

Expected: a handshake, six tools discovered, then the agent creating a table
and inserting a row — none of which this file implements.

## The two conceptual shifts

**1. Dynamic discovery.** You no longer write tool schemas. You call
`tools/list` and translate what comes back. *The agent's capabilities are now
defined by a process you did not write.*

**2. Delegated execution.** `tools/call` sends the request over a pipe. No
function in `app.py` touches SQLite.

## Why this is the pivot of the whole roadmap

Because MCP standardises the wire format, `tools/list` and `tools/call` are the
same JSON-RPC methods whether the server is Python, TypeScript, Go or Rust.

**That is the thesis of this project.** You do not need to modify the model.
You do not need to modify the MCP server. You need a man-in-the-middle on the
transport that:

- filters the `tools/list` **response** to what this agent identity may see, and
- rejects `tools/call` **requests** that violate policy or budget.

Lab 4 builds exactly that, and Lab 5 makes it decide.

## What this exposes: implicit trust

This script assumes `mcp-server-sqlite` is safe and that the model will use it
sensibly. `write_query` will happily execute `DROP TABLE`. **There is no policy
layer anywhere in this file.** Lab 7 shows how little effort it takes to
exploit that.

## Two gotchas worth internalising

### `inputSchema` is a wire alias, not an attribute

```python
"input_schema": tool.input_schema     # correct in mcp 2.x
"input_schema": tool.inputSchema      # AttributeError
```

The mcp 2.x Python SDK uses snake_case attributes with camelCase JSON aliases.
Same trap on `CallToolResult.is_error`.

### A dead server looks like a dead pipe

`mcp-server-sqlite` 0.1.0 is written against the mcp **1.x** low-level `Server`
API and crashes on import under mcp 2.x:

```
AttributeError: 'Server' object has no attribute 'list_resources'
```

Hence the pin in [`app.py`](app.py):

```python
args=["--with", "mcp<2", "mcp-server-sqlite", "--db-path", str(DB_PATH)]
```

When the server dies at startup, **the client cannot see why.** All it observes
is the pipe closing, surfaced as `MCPError: Connection closed` out of
`session.initialize()`. The real traceback is on the server's stderr.

> An MCP client can only ever report transport-level failure. That is exactly
> why the Lab 4 proxy forwards child stderr instead of swallowing it.

### And one more: relative paths

`--db-path test.db` resolves against whatever directory you ran from, and the
server inherits that cwd. [`app.py`](app.py) resolves against `__file__`
instead, so the lab always uses `lab3/test.db`.

## Exercises

1. Remove `--with mcp<2` and run it. Read the stderr traceback, then the
   client-side error. Notice how little the second tells you about the first.
2. Print `mcp_tools.tools[0]` in full. Every field there is a field gMCP can
   extend — compare with [`spec/gmcp-0.1.schema.json`](../spec/gmcp-0.1.schema.json).
3. Ask the agent to drop the table it just created. Nothing stops it. Keep that
   result in mind through Lab 5.

---

**Next:** [Lab 4 — The Proxy](../lab4/) slides a Go binary into that pipe and
starts reading every message.
