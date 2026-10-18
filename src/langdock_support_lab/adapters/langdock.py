import asyncio
from datetime import timezone
from email.utils import parsedate_to_datetime
import math
import httpx
from ..safety import strict_json
from .base import observation

AGENT_TEXT = "Reply with the word READY. This is a synthetic connectivity check."
KNOWLEDGE_TEXT = "LAB-RB-AUTH synthetic authentication runbook"


def retry_hint(headers, now):
    values = headers.get_list("retry-after")
    if len(values) != 1 or len(values[0]) > 128:
        return None
    value = values[0]
    if value.isascii() and value.isdigit():
        return min(int(value), 300)
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return min(300, max(0, math.ceil((date.astimezone(timezone.utc) - now).total_seconds())))
    except (ValueError, TypeError, OverflowError):
        return None


def parse_success(operation, data):
    if not isinstance(data, dict):
        raise ValueError("shape")
    if operation == "agent_completion":
        rows = data["messages"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise ValueError("messages")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row.get("role") != "assistant" or not isinstance(row.get("content"), str):
                raise ValueError("message")
        if not any(row["content"].strip() for row in rows):
            raise ValueError("empty")
        return observation("OK", 200, response_shape_valid=True, result_count=len(rows), nonempty_text=True,
                           probe_expectation_met=any(row["content"].strip().casefold() == "ready" for row in rows))
    rows = data["result"]
    if data.get("status") != "success" or not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("results")
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in ("id", "text", "subsource", "subname")) or not row["id"]:
            raise ValueError("item")
        similarity = row.get("similarity")
        if type(similarity) not in (int, float) or not math.isfinite(similarity) or not 0 <= similarity <= 1:
            raise ValueError("similarity")
        if type(row.get("index")) is not int or row["index"] < 0 or "url" not in row or (row["url"] is not None and not isinstance(row["url"], str)):
            raise ValueError("item")
    return observation("OK" if rows else "OK_EMPTY", 200, response_shape_valid=True, result_count=len(rows),
                       probe_expectation_met=any("LAB-RB-AUTH" in row["text"] for row in rows))


async def attempt(operation, run_id, key, agent_id, transport, now, deadline=25):
    headers = {"Accept": "application/json"}
    if key is not None:
        headers["Authorization"] = "Bearer " + key
    if operation == "agent_completion":
        path = "/agent/v1/chat/completions"
        body = {"agentId": agent_id, "messages": [{"id": "msg_" + run_id, "role": "user", "parts": [{"type": "text", "text": AGENT_TEXT}]}], "stream": False}
    else:
        path, body = "/knowledge/search", {"query": KNOWLEDGE_TEXT}
    status = None
    try:
        async with asyncio.timeout(deadline):
            async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                                        timeout=httpx.Timeout(connect=5, read=20, write=5, pool=1),
                                        limits=httpx.Limits(max_connections=4)) as client:
                async with client.stream("POST", "https://api.langdock.com" + path, headers=headers, json=body) as response:
                    status = response.status_code
                    received_at = now()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 1048576:
                            if status == 200:
                                return observation("UPSTREAM_PROTOCOL", status, response_shape_valid=False)
                            break
                        if status == 200:
                            chunks.append(chunk)
                    if status != 200:
                        code = {401: "UPSTREAM_AUTH", 403: "UPSTREAM_PERMISSION", 404: "UPSTREAM_NOT_FOUND", 429: "UPSTREAM_THROTTLED", 408: "UPSTREAM_TIMEOUT", 504: "UPSTREAM_TIMEOUT", 524: "UPSTREAM_TIMEOUT"}.get(status)
                        code = code or ("UPSTREAM_UNAVAILABLE" if 500 <= status <= 599 else "UPSTREAM_REJECTED" if 400 <= status <= 499 else "UPSTREAM_PROTOCOL")
                        return observation(code, status, retry_after_seconds=retry_hint(response.headers, received_at) if status == 429 else None)
                    if response.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                        raise ValueError("content-type")
                    return parse_success(operation, strict_json(b"".join(chunks).decode("utf-8")))
    except (TimeoutError, httpx.TimeoutException):
        return observation("UPSTREAM_TIMEOUT", status)
    except httpx.TransportError:
        return observation("UPSTREAM_NETWORK", status)
    except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
        return observation("UPSTREAM_PROTOCOL", status, response_shape_valid=False)
