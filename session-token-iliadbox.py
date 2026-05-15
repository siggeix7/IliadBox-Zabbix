#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import socket
import sys
import urllib.error
import urllib.request


DEFAULT_TIMEOUT = 10.0


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def get_timeout():
    raw_value = os.environ.get("ILIADBOX_TIMEOUT", str(DEFAULT_TIMEOUT))
    try:
        return float(raw_value)
    except ValueError:
        fail("ILIADBOX_TIMEOUT must be a number")


def parse_args(argv):
    if len(argv) not in (5, 6):
        fail(
            "Usage: session-token-iliadbox.py "
            "<app_token> <freebox_ip> <api_version> <app_id> [http|https]"
        )

    app_token, freebox_ip, api_version, app_id = argv[1:5]
    protocol = argv[5] if len(argv) == 6 else os.environ.get("ILIADBOX_PROTOCOL", "http")
    missing = [
        name
        for name, value in (
            ("app_token", app_token),
            ("freebox_ip", freebox_ip),
            ("api_version", api_version),
            ("app_id", app_id),
            ("protocol", protocol),
        )
        if not value
    ]
    if missing:
        fail("Missing required argument(s): " + ", ".join(missing))

    protocol = protocol.strip().rstrip(":/").lower()
    if protocol not in ("http", "https"):
        fail("protocol must be http or https")

    return app_token, freebox_ip.strip().rstrip("/"), api_version.strip("/"), app_id, protocol


def request_json(url, method="GET", payload=None, timeout=DEFAULT_TIMEOUT):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} from {url}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Cannot reach {url}: {error.reason}") from error
    except socket.timeout as error:
        raise RuntimeError(f"Timeout connecting to {url}") from error

    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Invalid JSON from {url}: {error}") from error


def result_value(data, key):
    result = data.get("result")
    if not isinstance(result, dict):
        return None
    return result.get(key)


def main(argv):
    app_token, freebox_ip, api_version, app_id, protocol = parse_args(argv)
    timeout = get_timeout()
    base_url = f"{protocol}://{freebox_ip}/api/{api_version}"

    try:
        login_data = request_json(f"{base_url}/login/", timeout=timeout)
        challenge = result_value(login_data, "challenge")
        if not challenge:
            fail("Challenge not found in login response")

        digest = hmac.new(
            app_token.encode("utf-8"),
            challenge.encode("utf-8"),
            hashlib.sha1,
        ).hexdigest()

        session_data = request_json(
            f"{base_url}/login/session/",
            method="POST",
            payload={"app_id": app_id, "password": digest},
            timeout=timeout,
        )
    except RuntimeError as error:
        fail(str(error))

    if session_data.get("success") is not True:
        fail("Login failed: " + json.dumps(session_data, ensure_ascii=False))

    session_token = result_value(session_data, "session_token")
    if not session_token:
        fail("Session token not found in login response")

    print(session_token)


if __name__ == "__main__":
    main(sys.argv)
