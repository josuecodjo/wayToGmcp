"""Agent workload identity — introduced in Lab 5, used by Labs 5-9.

WHY AN AGENT NEEDS AN IDENTITY OF ITS OWN
    The instinct is to reuse the human's credentials: the agent acts "as"
    the user who launched it. That collapses under the first prompt injection,
    because the agent now wields every permission that person holds, and the
    audit log records the human's name against actions they never chose.

    An agent is a workload, not a person. It gets its own identity, scoped to
    the job it was deployed to do, and an audit trail that names it.

WHY JWT HERE AND SPIFFE IN PRODUCTION
    Production issues SVIDs from SPIRE: identity attested from properties of
    the running workload (its image, its node, its k8s service account),
    delivered over a local socket, rotated automatically, never a shared
    secret sitting in an environment variable.

    Running SPIRE is a lab in itself, so we mint an HS256 JWT whose `sub` is a
    SPIFFE ID. Every consumer downstream — the Rego policy, the proxy's
    authorisation call, the Redis budget key in Lab 6, the audit log — reads
    exactly the same claim shape it would read from a real SVID. Swapping the
    issuer later changes this file and nothing else.

    The shared secret below is a *lab* secret. It is checked into the repo on
    purpose, so nobody is tempted to believe it is protecting anything.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import jwt  # PyJWT

# Deliberately weak and public. Real deployments verify an asymmetric
# signature against a JWKS the issuer publishes; nothing verifying a token
# should ever hold the material needed to mint one.
LAB_SECRET = "way-to-ai-lab-secret-not-for-production"

TRUST_DOMAIN = "spiffe://way-to-ai"


@dataclass(frozen=True)
class AgentIdentity:
    """One deployable agent persona.

    `roles` is what the Rego RBAC rule consumes. `break_glass` is the ABAC
    escalation claim required by any tool whose descriptor says
    risk_tier=critical — holding the role is necessary but not sufficient.
    """

    name: str
    roles: list[str] = field(default_factory=list)
    break_glass: bool = False
    description: str = ""

    @property
    def spiffe_id(self) -> str:
        return f"{TRUST_DOMAIN}/agent/{self.name}"

    def token(self, ttl_seconds: int = 900, secret: str | None = None) -> str:
        """Mint a short-lived signed token for this identity.

        Short TTLs are not decoration. A leaked agent token is a leaked set of
        tool permissions, and 15 minutes is the difference between an incident
        and a breach. Production rotates far faster than this.
        """
        now = int(time.time())
        claims = {
            "sub": self.spiffe_id,
            "roles": list(self.roles),
            "break_glass": self.break_glass,
            "iat": now,
            "exp": now + ttl_seconds,
            "aud": "gmcp-proxy",
            "iss": f"{TRUST_DOMAIN}/issuer/lab",
        }
        return jwt.encode(claims, secret or LAB_SECRET, algorithm="HS256")


# --------------------------------------------------------------------------
# THE CAST
#
# These three personas run through Labs 5-9 unchanged. They are ordered by
# privilege so that the same task, run as each of them in turn, produces three
# visibly different outcomes — which is the demo at the heart of Lab 5.
# --------------------------------------------------------------------------

ANALYST = AgentIdentity(
    name="analyst",
    roles=["reader"],
    description="Read-only reporting agent. Least privilege — the safe default.",
)

ETL = AgentIdentity(
    name="etl",
    roles=["reader", "writer"],
    description="Loads rows into existing tables. Writes data, never schema.",
)

ADMIN = AgentIdentity(
    name="admin",
    roles=["reader", "writer", "schema_admin"],
    break_glass=True,
    description="Schema owner. Break-glass claim present; every call audited.",
)

CAST = {"analyst": ANALYST, "etl": ETL, "admin": ADMIN}


def get(name: str) -> AgentIdentity:
    """Look up a persona by short name, with a helpful error for typos."""
    try:
        return CAST[name]
    except KeyError:
        raise SystemExit(
            f"unknown identity {name!r}. Available: {', '.join(CAST)}"
        ) from None


def proxy_env(identity: AgentIdentity, registry: os.PathLike | str, **extra) -> dict:
    """Build the environment the Go proxy needs to authenticate this agent.

    The token is passed to the proxy as an environment variable because the
    proxy is spawned as a child process over stdio — there is no HTTP header
    to put it in. An HTTP/SSE MCP transport would carry it as
    `Authorization: Bearer ...` and nothing else about the design would change.
    """
    env = {
        **os.environ,
        "GMCP_AGENT_TOKEN": identity.token(),
        "GMCP_JWT_SECRET": LAB_SECRET,
        "GMCP_REGISTRY": str(registry),
    }
    env.update({k: str(v) for k, v in extra.items()})
    return env
