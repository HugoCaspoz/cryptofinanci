"""Browser-origin policy shared by HTTP mutations and WebSocket handshakes."""
import os
from urllib.parse import urlsplit


def trusted_origin(headers):
    origin = headers.get("origin")
    if origin is None:
        # Non-browser clients (health checks, CLI, tests) do not send Origin.
        return headers.get("sec-fetch-site") != "cross-site"
    if origin == "null":
        return False
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.path or parsed.query or parsed.fragment:
            return False
        canonical = f"{parsed.scheme}://{parsed.netloc.lower()}"
        configured = {o.strip().rstrip("/").lower() for o in os.getenv("APP_ALLOWED_ORIGINS", "").split(",") if o.strip()}
        if configured:
            return canonical in configured
        host = headers.get("host", "").lower()
        return parsed.netloc.lower() == host or (parsed.port == (443 if parsed.scheme == "https" else 80) and parsed.hostname.lower() == host)
    except ValueError:
        return False
