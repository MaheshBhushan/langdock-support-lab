MESSAGES = {
    "OK": "The probe returned a valid nonempty response.",
    "OK_EMPTY": "The search returned no results; relevance and sharing remain unknown.",
    "UPSTREAM_AUTH": "Upstream authentication failed. Check backend credentials and scope.",
    "UPSTREAM_PERMISSION": "The upstream request was denied. Check scope and resource sharing.",
    "UPSTREAM_NOT_FOUND": "The upstream resource was not found; configuration remains uncertain.",
    "UPSTREAM_THROTTLED": "The upstream request was throttled. Consider the bounded manual retry hint.",
    "UPSTREAM_TIMEOUT": "The attempt timed out. Upstream completion and billing remain uncertain.",
    "UPSTREAM_UNAVAILABLE": "Upstream availability is unknown after a server error.",
    "UPSTREAM_REJECTED": "The upstream request was rejected. Review the request contract.",
    "UPSTREAM_PROTOCOL": "The upstream response did not match the supported protocol.",
    "UPSTREAM_NETWORK": "The transport failed. Connectivity requires investigation.",
    "RUN_INTERRUPTED": "The attempt was interrupted. Its upstream outcome is unknown; inspect before retry.",
}


def observation(code, status=None, **fields):
    return {
        "code": code, "upstream_status": status, "duration_ms": 0,
        "retryable": code in {"UPSTREAM_THROTTLED", "UPSTREAM_TIMEOUT", "UPSTREAM_UNAVAILABLE", "UPSTREAM_NETWORK"},
        "retry_after_seconds": None, "attempt_count": 1, "response_shape_valid": None,
        "result_count": None, "nonempty_text": None, "probe_expectation_met": None,
        "message": MESSAGES[code], **fields,
    }
