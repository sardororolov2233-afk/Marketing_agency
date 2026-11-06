import os
import sys
from pathlib import Path
from urllib.parse import parse_qs

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.api import app as fastapi_app

async def app(scope, receive, send):
    if scope["type"] == "http":
        qs = parse_qs(scope.get("query_string", b"").decode("utf-8"))
        if "path" in qs and qs["path"]:
            scope["path"] = "/" + qs["path"][0].lstrip("/")
    await fastapi_app(scope, receive, send)
