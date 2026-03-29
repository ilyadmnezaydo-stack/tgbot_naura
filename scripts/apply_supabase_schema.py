"""
Apply the local Supabase SQL schema through the Supabase Management API.

Requires:
- SUPABASE_URL
- SUPABASE_ACCESS_TOKEN (personal access token for the Management API)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "supabase" / "bot_schema.sql"
PROJECT_REF_RE = re.compile(r"^https://([^.]+)\.supabase\.co/?$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply bot_schema.sql to a Supabase project")
    parser.add_argument(
        "--file",
        default=str(DEFAULT_SCHEMA_PATH),
        help="Path to the SQL file to apply",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Request timeout in seconds",
    )
    return parser.parse_args()


def get_project_ref(supabase_url: str) -> str:
    match = PROJECT_REF_RE.match(supabase_url.strip())
    if not match:
        raise ValueError("SUPABASE_URL must look like https://<project-ref>.supabase.co")
    return match.group(1)


def load_config() -> tuple[str, str]:
    load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    access_token = os.getenv("SUPABASE_ACCESS_TOKEN", "").strip()

    if not supabase_url:
        raise RuntimeError("SUPABASE_URL is missing")
    if not access_token:
        raise RuntimeError(
            "SUPABASE_ACCESS_TOKEN is missing. Create a personal access token in Supabase and put it into .env."
        )

    return supabase_url, access_token


def apply_schema(sql_path: Path, timeout: int) -> None:
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_path}")

    supabase_url, access_token = load_config()
    project_ref = get_project_ref(supabase_url)
    sql = sql_path.read_text(encoding="utf-8").strip()
    if not sql:
        raise RuntimeError(f"SQL file is empty: {sql_path}")

    endpoint = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"
    response = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"query": sql},
        timeout=timeout,
    )

    if response.status_code >= 400:
        detail = response.text.strip()
        raise RuntimeError(f"Supabase API returned {response.status_code}: {detail}")

    print(f"Schema applied successfully via Management API to project {project_ref}.")
    if response.text.strip():
        try:
            payload = response.json()
        except json.JSONDecodeError:
            print(response.text.strip())
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    args = parse_args()
    try:
        apply_schema(Path(args.file).resolve(), timeout=args.timeout)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
