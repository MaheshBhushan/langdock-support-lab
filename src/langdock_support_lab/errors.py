MESSAGES = {
    "LOCAL_AUTH_REQUIRED": "Local authentication is required.",
    "LOCAL_FORBIDDEN": "This role cannot perform this operation.",
    "BROWSER_ORIGIN_DENIED": "Browser origins are not supported.",
    "INVALID_HOST": "The request host is not supported.",
    "INVALID_INPUT": "The request input is invalid.",
    "INVALID_JSON": "The request JSON is invalid.",
    "SENSITIVE_INPUT": "Sensitive input is not accepted.",
    "BODY_TOO_LARGE": "The request body exceeds the limit.",
    "UNSUPPORTED_MEDIA_TYPE": "JSON media type is required.",
    "GET_BODY_DENIED": "GET bodies are not supported.",
    "MODE_MISMATCH": "Request mode does not match server mode.",
    "LOCAL_CAPACITY": "All attempt slots are occupied.",
    "NOT_FOUND": "The resource does not exist.",
    "VERSION_CONFLICT": "The incident version has changed.",
    "INVALID_TRANSITION": "The incident transition is not allowed.",
    "RUN_ALREADY_ATTACHED": "The run is already attached.",
    "INCIDENT_EXISTS": "An incident already exists for this run.",
    "STORAGE_BUSY": "Storage is temporarily busy.",
    "STORAGE_UNAVAILABLE": "Storage is unavailable.",
    "INTERNAL_ERROR": "An internal error occurred.",
}


class LabError(Exception):
    def __init__(self, code, status=422, details=None):
        self.code, self.status, self.details = code, status, details or []
        super().__init__(code)
