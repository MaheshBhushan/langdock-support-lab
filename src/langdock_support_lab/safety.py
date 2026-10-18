import json
import math
import re
import unicodedata
from .errors import LabError


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite")

    def finite_number(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite")
        return number

    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid, parse_float=finite_number)


def sensitive(text, secrets=()):
    value = unicodedata.normalize("NFKC", text)
    return any(secret and unicodedata.normalize("NFKC", secret) in value for secret in secrets) or bool(re.search(
        r"(?i)\bbearer\s+\S+|-----BEGIN .*PRIVATE KEY-----|\b(?:api[_-]key|token|password|secret)\s*[:=]\s*\S+", value))


def free_text(text, secrets=()):
    if sensitive(text, secrets):
        raise LabError("SENSITIVE_INPUT")
    if any(unicodedata.category(c).startswith("C") for c in text):
        raise LabError("INVALID_INPUT")
    return text


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
