#!/usr/bin/env python3
import argparse
import json
import os
import sys
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_ORIGIN = "http://127.0.0.1:4173"


def build_headers(secret):
    headers = {
        "Accept": "application/json",
        "Origin": DEFAULT_ORIGIN,
    }
    if secret:
        headers["x-dashboard-secret"] = secret
    return headers


def check(condition, label, details=""):
    status = "PASS" if condition else "FAIL"
    print(f"{status} {label}{f' - {details}' if details else ''}")
    return bool(condition)


def request_json(method, base_url, path, headers, **kwargs):
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    data = kwargs.get("data")
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}

    request = Request(url, data=data, headers=headers, method=method)

    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status_code = response.status
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status_code = exc.code
    except URLError as exc:
        return type("SmokeResponse", (), {"ok": False, "status_code": 0})(), {"error": str(exc)}

    try:
        body = json.loads(raw) if raw else {}
    except Exception:
        body = {"text": raw[:400]}

    return type("SmokeResponse", (), {"ok": 200 <= status_code < 300, "status_code": status_code})(), body


def main():
    parser = argparse.ArgumentParser(description="Instaagent production smoke checks")
    parser.add_argument("--api", default=os.getenv("API_BASE", "https://agent-1-xi6h.onrender.com"))
    parser.add_argument("--secret", default=os.getenv("DASHBOARD_SECRET", ""))
    args = parser.parse_args()

    headers = build_headers(args.secret)
    failures = 0

    response, body = request_json("GET", args.api, "/api/health", headers)
    failures += not check(response.ok and body.get("status") == "ok", "health endpoint", str(response.status_code))

    response, body = request_json("GET", args.api, "/api/conversations", headers)
    failures += not check(response.ok and body.get("status") == "ok", "conversations endpoint", str(response.status_code))

    conversations = body.get("data") or []
    first_id = conversations[0].get("id") if conversations else ""
    failures += not check(bool(first_id), "at least one conversation", f"{len(conversations)} found")

    if first_id:
        response, body = request_json("GET", args.api, f"/api/conversation/{first_id}", headers)
        failures += not check(response.ok and body.get("status") == "ok", "conversation messages endpoint", str(response.status_code))

    response, body = request_json("GET", args.api, "/api/stats", headers)
    failures += not check(response.ok and body.get("status") == "ok", "stats endpoint", str(response.status_code))

    response, body = request_json("GET", args.api, "/api/businesses", headers)
    failures += not check(response.ok and body.get("status") == "ok", "businesses endpoint", str(response.status_code))

    response, _ = request_json(
        "OPTIONS",
        args.api,
        "/api/conversations",
        {
            "Origin": DEFAULT_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-dashboard-secret",
        },
    )
    failures += not check(response.ok, "CORS preflight", str(response.status_code))

    response, _ = request_json("GET", args.api, "/debug/businesses", {"Accept": "application/json"})
    expected_debug_status = 401 if args.secret else 200
    failures += not check(response.status_code == expected_debug_status, "debug route auth behavior", str(response.status_code))

    if failures:
        print(f"\n{failures} smoke check(s) failed.")
        return 1

    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
