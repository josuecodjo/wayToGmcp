"""labkit — the only code shared across every lab in this repo.

It deliberately contains **no agent logic**. Every lab writes its own ReAct
loop, its own policy checks and its own MCP wiring in full, so a lab can be
read top-to-bottom without chasing an abstraction, and so you can diff one lab
against the previous to see exactly what a quarter added.

What lives here is only what would be genuinely wasteful to repeat:

    console.py    event vocabulary and formatting, so nine labs print in one
                  voice and transcripts stay comparable across the roadmap
    identity.py   agent workload identity — introduced in Lab 5, used by 5-9

"""
