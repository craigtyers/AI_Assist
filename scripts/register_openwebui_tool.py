#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL_FILE = ROOT / "openwebui_tools" / "recite_repo_rag_tool.py"

TOOL_ID = "recite_repo_rag_tool"
TOOL_NAME = "Recite Repo RAG"
TOOL_DESCRIPTION = "Search and QA over recite-api, recite-toolbar, and Recite.toolbar.launcher via local RAG API."


def http_json(url: str, method: str = "GET", token: str | None = None, payload: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
            return resp.status, json.loads(data) if data else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001
            parsed = {"detail": raw}
        return exc.code, parsed


def sign_in(base_url: str, email: str, password: str) -> str:
    status, data = http_json(
        f"{base_url}/api/v1/auths/signin",
        method="POST",
        payload={"email": email, "password": password},
    )
    if status != 200:
        raise RuntimeError(f"Sign-in failed ({status}): {data}")

    token = data.get("token")
    if not token:
        raise RuntimeError("Sign-in response missing token")
    return token


def upsert_tool(base_url: str, token: str, tool_content: str) -> dict:
    payload = {
        "id": TOOL_ID,
        "name": TOOL_NAME,
        "content": tool_content,
        "meta": {"description": TOOL_DESCRIPTION},
        "access_grants": [],
    }

    status, existing = http_json(f"{base_url}/api/v1/tools/id/{TOOL_ID}", token=token)
    if status == 200:
        status, data = http_json(
            f"{base_url}/api/v1/tools/id/{TOOL_ID}/update",
            method="POST",
            token=token,
            payload=payload,
        )
        if status != 200:
            raise RuntimeError(f"Tool update failed ({status}): {data}")
        return {"action": "updated", "response": data}

    if status in (401, 404):
        status, data = http_json(
            f"{base_url}/api/v1/tools/create",
            method="POST",
            token=token,
            payload=payload,
        )
        if status != 200:
            raise RuntimeError(f"Tool create failed ({status}): {data}")
        return {"action": "created", "response": data}

    raise RuntimeError(f"Unexpected tool lookup response ({status}): {existing}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update the Recite RAG tool in Open WebUI")
    parser.add_argument("--openwebui-url", default=os.getenv("OPENWEBUI_URL", "http://127.0.0.1:3000"))
    parser.add_argument("--email", default=os.getenv("OPENWEBUI_EMAIL"))
    parser.add_argument("--password", default=os.getenv("OPENWEBUI_PASSWORD"))
    parser.add_argument("--token", default=os.getenv("OPENWEBUI_TOKEN"), help="Bearer token (optional).")
    args = parser.parse_args()

    if not TOOL_FILE.exists():
        print(f"Tool file not found: {TOOL_FILE}", file=sys.stderr)
        return 1

    token = args.token
    if not token:
        if not args.email or not args.password:
            print(
                "Provide OPENWEBUI_TOKEN or OPENWEBUI_EMAIL + OPENWEBUI_PASSWORD.",
                file=sys.stderr,
            )
            return 2
        token = sign_in(args.openwebui_url.rstrip("/"), args.email, args.password)

    tool_content = TOOL_FILE.read_text(encoding="utf-8")
    result = upsert_tool(args.openwebui_url.rstrip("/"), token, tool_content)

    print(json.dumps({"ok": True, **result}, indent=2))
    print("\nTool ready in Open WebUI: Recite Repo RAG")
    print("If needed, set tool valve 'rag_base_url' to: http://host.docker.internal:8088")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
