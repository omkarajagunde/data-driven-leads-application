#!/usr/bin/env python3
"""Manage API keys for the FastAPI server. Only a hash of each key is stored, so a key is
shown once, when it is created.

  python3 src/backend/api_keys.py create "acme builders"
  python3 src/backend/api_keys.py list
  python3 src/backend/api_keys.py revoke 3
"""
import argparse
import hashlib
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create").add_argument("label")
    sub.add_parser("list")
    sub.add_parser("revoke").add_argument("key_id", type=int)
    a = p.parse_args()
    with db.connect() as con:
        if a.cmd == "create":
            key = "ddl_" + secrets.token_urlsafe(32)
            row = con.execute(
                "INSERT INTO api_keys(key_hash, key_prefix, label) VALUES (%s,%s,%s) RETURNING key_id",
                (hashlib.sha256(key.encode()).hexdigest(), key[:8], a.label)).fetchone()
            print(f"key {row['key_id']} for '{a.label}' (shown once, store it now):\n{key}")
        elif a.cmd == "list":
            for r in con.execute("SELECT key_id, key_prefix, label, created_at, last_used_at, revoked_at FROM api_keys ORDER BY key_id"):
                state = "revoked" if r["revoked_at"] else "active"
                print(f"{r['key_id']:>4}  {r['key_prefix']}…  {state:8} {r['label']}  created {r['created_at']:%Y-%m-%d}"
                      f"  last used {r['last_used_at'] or 'never'}")
        else:
            n = con.execute("UPDATE api_keys SET revoked_at = now() WHERE key_id = %s AND revoked_at IS NULL",
                            (a.key_id,)).rowcount
            print("revoked" if n else "no active key with that id")


if __name__ == "__main__":
    main()
