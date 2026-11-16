"""Load secrets from the repo-root .env file into os.environ.

Rules:
  * Real environment variables always win; .env only fills in what is missing.
  * Values are never printed or logged by this module.
  * Supports KEY=value, KEY="value", KEY='value', `export KEY=value`, blank lines and # comments.
  * No third-party dependency, so it works before `pip install -r requirements.txt`.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root (this file is in src/backend)
ENV_FILE = ROOT / ".env"


def load_dotenv(path: Path | None = None) -> None:
    path = path or ENV_FILE
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)


def require(key: str) -> str:
    """Return a required secret, loading .env first. Exits with a clear message if missing."""
    load_dotenv()
    value = os.environ.get(key)
    if not value:
        raise SystemExit(
            f"{key} is not set. Put it in {ENV_FILE} (see .env.example) "
            f"or export it in your shell."
        )
    return value
