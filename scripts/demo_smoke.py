"""Local smoke check; requires running API. No credentials needed."""
import json
import sys
from urllib.request import urlopen

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
for path in ("/health/live", "/health/ready", "/openapi.json"):
    with urlopen(base + path, timeout=10) as resp:
        doc = json.load(resp)
        print(f"{resp.status} {path} ->", doc.get("status", f"{len(doc.get('paths', {}))} API paths"))
