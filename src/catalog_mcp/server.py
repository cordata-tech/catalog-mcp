"""The MCP server: five read-only tools and two resources over the catalog.

Every tool is a lookup or an evaluation — the post's inclusion rule: a question
gets a tool when its answer already exists as a record in the governance plane.
"""

from __future__ import annotations

import json
import re
from typing import Annotated

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.types import ToolAnnotations
from pipeline_runtime.errors import UnknownTagKey, UnknownTagValue
from pydantic import BaseModel, Field

from . import PROTOCOL_REVISION, __version__
from .catalog import Catalog, Column, Dataset, reaches

# Display metadata only — § 4 of the post. Read-only holds because no handler
# writes and every object handed out is frozen, not because of these hints.
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)

# The lists vary by the caller's granted scopes, so a shared cache must never
# serve one caller's catalog to another: private, and short.
CACHE = {
    method: CacheHint(ttl_ms=60_000, scope="private")
    for method in ("tools/list", "resources/list", "resources/templates/list", "resources/read")
}

DomainArg = Annotated[
    str,
    Field(
        description="Owning domain, e.g. fraud or policy",
        # Mirrored into an `Mcp-Param-Domain` header, so a gateway can route on
        # the domain without parsing the body. A domain name is safe to expose;
        # a subject identifier would not be.
        json_schema_extra={"x-mcp-header": "Domain"},
    ),
]
TableArg = Annotated[str, Field(description="Table name, e.g. transactions_scored")]


def scope_for(domain: str) -> str:
    return f"catalog:{domain}:read"


def _granted(catalog: Catalog) -> set[str]:
    """The domains this request may see.

    Over stdio there is no token: the host started the process, and the process
    boundary is the authorization (§ 5). Over HTTP every request carries one.
    """
    token = get_access_token()
    if token is None:
        return set(catalog.domains())
    return {d for d in catalog.domains() if scope_for(d) in token.scopes}


def _require(catalog: Catalog, domain: str) -> None:
    # Re-checked on every call: a handle is a name, not a capability. The HTTP
    # layer answers 403 before this runs; this is the second line, not the only one.
    if domain not in _granted(catalog):
        raise ToolError(f"insufficient_scope: {scope_for(domain)} is required")


class DomainInfo(BaseModel):
    name: str
    owners: list[str]
    datasets: list[str]


class Domains(BaseModel):
    domains: list[DomainInfo]


class Resolved(BaseModel):
    tags: dict[str, str]


class GrantCheck(BaseModel):
    reaches: bool = Field(description="Whether the expression reaches any column")
    columns: list[str] = Field(description="The columns the expression reaches")


class Match(BaseModel):
    domain: str
    table: str
    columns: list[str]


class Matches(BaseModel):
    datasets: list[Match]


def build_server(
    catalog: Catalog | None = None,
    *,
    auth: AuthSettings | None = None,
    token_verifier: TokenVerifier | None = None,
) -> MCPServer:
    catalog = catalog or Catalog()
    server = MCPServer(
        name="cordata-catalog-mcp",
        title="Cordata catalog",
        description="Read-only answers about datasets, ownership and LF-tag policy.",
        version=__version__,
        website_url="https://cordata.tech/en/blog/governed-mesh-over-mcp",
        instructions=(
            "A read-only catalog. It answers questions about datasets — ownership, "
            "schema, LF-tag policy — never from them: no rows, no per-user grant "
            f"listings, no cross-domain joins. Verified against MCP {PROTOCOL_REVISION}."
        ),
        auth=auth,
        token_verifier=token_verifier,
        cache_hints=CACHE,
        subscriptions=False,
    )

    @server.tool(title="Domains and owners", annotations=READ_ONLY)
    def list_domains() -> Domains:
        """What domains exist, and who owns them. Only the domains this caller may read."""
        granted = _granted(catalog)
        by_domain: dict[str, list[Dataset]] = {}
        for (domain, _), ds in catalog.datasets.items():
            if domain in granted:
                by_domain.setdefault(domain, []).append(ds)
        return Domains(
            domains=[
                DomainInfo(
                    name=domain,
                    owners=sorted({ds.metadata.owner for ds in found}),
                    datasets=sorted(t for (d, t) in catalog.datasets if d == domain),
                )
                for domain, found in sorted(by_domain.items())
            ]
        )

    @server.tool(title="Dataset lookup", annotations=READ_ONLY)
    def get_dataset(domain: DomainArg, table: TableArg) -> Dataset:
        """Schema, ownership and policy tags for one published dataset."""
        _require(catalog, domain)
        dataset = catalog.get(domain, table)
        if dataset is None:
            raise ToolError(f"no dataset {domain}/{table}")
        return dataset

    @server.tool(title="Validate a tag set", annotations=READ_ONLY)
    def resolve_lf_tag(tags: dict[str, str]) -> Resolved:
        """Is this tag set valid against the governance-owned ontology?

        Runs the same `policy.resolve()` the executor runs, and fails the same way.
        """
        try:
            return Resolved(tags=catalog.resolve(tags))
        except (UnknownTagKey, UnknownTagValue) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(title="Would a grant reach a dataset", annotations=READ_ONLY)
    def check_grant_expression(
        domain: DomainArg,
        table: TableArg,
        expression: Annotated[
            dict[str, list[str]],
            Field(description="Tag key to permitted values, e.g. {'sensitivity': ['high']}"),
        ],
    ) -> GrantCheck:
        """Would this tag-based grant expression reach this dataset, and which columns?"""
        _require(catalog, domain)
        try:
            catalog.validate_expression(expression)
        except (UnknownTagKey, UnknownTagValue) as exc:
            raise ToolError(str(exc)) from exc
        dataset = catalog.get(domain, table)
        if dataset is None:
            raise ToolError(f"no dataset {domain}/{table}")
        columns = [c.name for c in dataset.columns if reaches(expression, c.lf_tags)]
        return GrantCheck(reaches=bool(columns), columns=columns)

    @server.tool(title="Find datasets by tag", annotations=READ_ONLY)
    def find_datasets(tags: dict[str, str]) -> Matches:
        """Which datasets carry these tag values — for example subject_type=customer.

        Answers which datasets hold a kind of data, and in which columns. It
        cannot say where one person's rows are: that is a query against the data,
        and this server never reads data. Only domains this caller may read.
        """
        try:
            wanted = catalog.resolve(tags)
        except (UnknownTagKey, UnknownTagValue) as exc:
            raise ToolError(str(exc)) from exc
        granted = _granted(catalog)
        found = []
        for (domain, table), ds in sorted(catalog.datasets.items()):
            if domain not in granted:
                continue
            cols = [c.name for c in ds.columns if _carries(c, wanted)]
            if cols:
                found.append(Match(domain=domain, table=table, columns=cols))
        return Matches(datasets=found)

    @server.resource(
        "cordata://ontology/lf-tags",
        name="lf-tag-ontology",
        mime_type="application/json",
    )
    def ontology() -> str:
        """The governance-owned LF-tag vocabulary every tag is checked against."""
        return json.dumps(catalog.ontology())

    @server.resource(
        "cordata://domain/{domain}/dataset/{table}",
        name="dataset",
        mime_type="application/json",
    )
    def dataset(domain: str, table: str) -> str:
        """One dataset's schema, ownership and policy tags."""
        if domain not in _granted(catalog):
            raise ResourceError(f"insufficient_scope: {scope_for(domain)} is required")
        found = catalog.get(domain, table)
        if found is None:
            raise ResourceError(f"no dataset {domain}/{table}")
        return found.model_dump_json()

    return server


def _carries(column: Column, wanted: dict[str, str]) -> bool:
    return all(column.lf_tags.get(k) == v for k, v in wanted.items())


DATASET_URI = re.compile(r"^cordata://domain/(?P<domain>[^/]+)/dataset/[^/]+$")
# The tools whose answer is scoped to one domain, named in their `domain` argument.
DOMAIN_TOOLS = frozenset({"get_dataset", "check_grant_expression"})
