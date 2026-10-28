"""Run after configuring .env. Exports the same schema served at /openapi.json."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app

output = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
output.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Exported {len(app.openapi()['paths'])} paths to {output}")
