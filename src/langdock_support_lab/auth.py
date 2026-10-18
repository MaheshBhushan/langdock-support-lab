import hmac
from .errors import LabError


def authenticate(headers, tokens):
    values = [v for k, v in headers if k.lower() == b"authorization"]
    supplied = values[0].decode("latin1") if len(values) == 1 else ""
    found = None
    for role, token in tokens.items():
        match = hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode())
        if match:
            found = role
    if found is None:
        raise LabError("LOCAL_AUTH_REQUIRED", 401)
    return found
