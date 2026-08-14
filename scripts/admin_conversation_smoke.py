"""Interactively smoke-test the admin conversation flow against a running API."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from app.core.config import Settings


class APIRequestError(RuntimeError):
    """A safe representation of an HTTP response that prevented the smoke flow."""


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    """Send one JSON request with standard-library HTTP support only."""

    encoded_body = (
        json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    )
    request_headers = {"Accept": "application/json"}
    if encoded_body is not None:
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=encoded_body,
        headers=request_headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 -- CLI target is explicit.
            payload = response.read().decode("utf-8")
    except HTTPError as error:
        payload = error.read().decode("utf-8", errors="replace")
        raise APIRequestError(f"{method} {path} failed ({error.code}): {payload}") from error
    except URLError as error:
        raise APIRequestError(f"Cannot reach the API at {base_url}: {error.reason}") from error

    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as error:
        raise APIRequestError(f"{method} {path} returned invalid JSON: {payload}") from error
    if not isinstance(decoded, dict):
        raise APIRequestError(f"{method} {path} returned an unexpected JSON payload.")
    return decoded


def _stream_request(
    base_url: str,
    method: str,
    path: str,
    *,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float = 90,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield named JSON SSE events with no external client dependency."""

    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            **headers,
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 -- CLI target is explicit.
            event_name = "message"
            data_lines: list[str] = []
            for raw_line in response:
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if not line:
                    if data_lines:
                        try:
                            payload = json.loads("\n".join(data_lines))
                        except json.JSONDecodeError as error:
                            raise APIRequestError("SSE event contained invalid JSON.") from error
                        if not isinstance(payload, dict):
                            raise APIRequestError("SSE event contained an unexpected payload.")
                        yield event_name, payload
                    event_name = "message"
                    data_lines = []
                elif line.startswith("event:"):
                    event_name = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").strip())
    except HTTPError as error:
        payload = error.read().decode("utf-8", errors="replace")
        raise APIRequestError(f"{method} {path} failed ({error.code}): {payload}") from error
    except URLError as error:
        raise APIRequestError(f"Cannot reach the API at {base_url}: {error.reason}") from error


def _admin_credentials(settings: Settings) -> tuple[str, str]:
    """Load the bootstrap admin credentials from the project's `.env` file."""

    email = settings.bootstrap_admin_email
    password = (
        settings.bootstrap_admin_password.get_secret_value()
        if settings.bootstrap_admin_password is not None
        else ""
    )
    if not email or not password:
        raise APIRequestError(
            "BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD must be set in .env."
        )
    return email, password


def run(base_url: str) -> int:
    """Log in as the configured admin, create a conversation, and read terminal turns."""

    settings = Settings()
    email, password = _admin_credentials(settings)
    login = _request(
        base_url,
        "POST",
        "/api/v1/auth/login",
        body={"email": email, "password": password},
    )
    access_token = login.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise APIRequestError("Login succeeded without an access token.")
    authorization = {"Authorization": f"Bearer {access_token}"}

    conversation = _request(
        base_url,
        "POST",
        "/api/v1/conversations",
        body={},
        headers=authorization,
    )
    conversation_id = conversation.get("id")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise APIRequestError("Conversation creation succeeded without an id.")

    print(f"Logged in as {email}; created conversation {conversation_id}.")
    print("Enter a message. Type /exit or press Ctrl-D to finish.")
    while True:
        try:
            user_input = input("you> ").strip()
        except EOFError:
            print()
            break
        if user_input in {"/exit", "/quit"}:
            break
        if not user_input:
            continue

        received_tokens = False
        for event, payload in _stream_request(
            base_url,
            "POST",
            f"/api/v1/conversations/{conversation_id}/messages",
            body={
                "input": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_input}],
                },
                "stream": True,
            },
            headers={**authorization, "Idempotency-Key": str(uuid4())},
        ):
            if event == "response.output_text.delta":
                delta = payload.get("delta")
                if isinstance(delta, str):
                    if not received_tokens:
                        prefix = f"assistant [{payload.get('item_id', 'unknown')}]> "
                        print(prefix, end="", flush=True)
                        received_tokens = True
                    print(delta, end="", flush=True)
            elif event == "response.completed":
                if received_tokens:
                    print()
                    continue
                response = payload.get("response")
                if not isinstance(response, dict):
                    raise APIRequestError("SSE completion event lacked a response object.")
                output = response.get("output")
                if not isinstance(output, list) or not output or not isinstance(output[0], dict):
                    raise APIRequestError("SSE completion event lacked an assistant output item.")
                content = output[0].get("content")
                if not isinstance(content, list) or not content or not isinstance(content[0], dict):
                    raise APIRequestError("SSE completion event lacked assistant output text.")
                answer = content[0].get("text")
                rendered_answer = (
                    answer if isinstance(answer, str) else json.dumps(response, ensure_ascii=False)
                )
                print(f"assistant [{response.get('id', 'unknown')}]> {rendered_answer}")
            elif event == "error":
                raise APIRequestError(
                    f"Stream failed: {payload.get('code', 'unknown_error')} — "
                    f"{payload.get('message', 'Unknown error.')}"
                )
    return 0


def main() -> int:
    """Parse the optional API address and execute the interactive smoke test."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        return run(args.base_url)
    except APIRequestError as error:
        print(f"Smoke test failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
