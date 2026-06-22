from typing import Optional
from sqlmodel import SQLModel, Field


class Cli(SQLModel, table=True):
    slug: str = Field(primary_key=True)            # opaque stable id
    lang: str                                       # adapter id: python/go/node/shell
    bucket: Optional[str] = None
    project: Optional[str] = None
    path: Optional[str] = None                      # data, not identity
    launch_spec: str = "{}"                         # JSON: {kind, entrypoint, args_schema}
    description: str = ""
    source_class: Optional[str] = None              # opaque; engine never branches on it
    health_cmd: Optional[str] = None
    health_status: str = "unknown"                   # healthy/unhealthy/unknown/stale
    health_checked_at: Optional[float] = None
    enabled: bool = True
    a2a_invokable: bool = False                     # reserved, unread in v1
    source_run_id: Optional[str] = None
    last_seen_at: Optional[float] = None
    updated_at: Optional[float] = None


class Capability(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    cli_slug: str = Field(foreign_key="cli.slug")
    intent_tags: str = ""                           # CSV controlled-vocab verbs
    input_types: str = ""                           # CSV registered typed ports
    output_types: str = ""                          # CSV registered typed ports
    side_effect: str = "unknown"                    # none/writes-fs/network/destructive/unknown
    confidence: str = "declared"                    # declared/inferred


class CliEdge(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    from_slug: str = Field(foreign_key="cli.slug")
    to_slug: str = Field(foreign_key="cli.slug")
    via_type: str
    recomputed_at: float = 0.0


class Subscriber(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str
    hmac_secret: str
    seq: int = 0
    enabled: bool = True


class Delivery(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    subscriber_id: int = Field(foreign_key="subscriber.id")
    event_id: str
    event_type: str
    payload: str
    attempts: int = 0
    delivered: bool = False
    dead_lettered: bool = False
