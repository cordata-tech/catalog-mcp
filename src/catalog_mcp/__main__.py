"""`cordata-catalog-mcp`: stdio by default, HTTP with a token issuer when asked."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import PROTOCOL_REVISION, __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cordata-catalog-mcp",
        description="A read-only MCP server over the cordata-pipeline-runtime example catalog.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__} (MCP {PROTOCOL_REVISION})",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="serve streamable HTTP instead of stdio; needs --issuer and --public-key",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--issuer", help="the one token issuer accepted, e.g. https://idp.example")
    parser.add_argument(
        "--public-key", type=Path, help="PEM file with the issuer's ES256 public key"
    )
    parser.add_argument(
        "--resource-url",
        help="this server's public URL, which tokens must name as audience "
        "(default: http://HOST:PORT/mcp)",
    )
    args = parser.parse_args(argv)

    if not args.http:
        from .server import build_server

        build_server().run("stdio")
        return 0

    if not (args.issuer and args.public_key):
        parser.error("--http needs --issuer and --public-key: HTTP is never served without auth")

    import uvicorn
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    from .app import build_http_app

    app = build_http_app(
        load_pem_public_key(args.public_key.read_bytes()),
        issuer=args.issuer,
        resource_url=args.resource_url or f"http://{args.host}:{args.port}/mcp",
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
