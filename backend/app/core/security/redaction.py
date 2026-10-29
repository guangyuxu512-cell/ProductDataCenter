from typing import Any


REDACTED_VALUE = "[REDACTED]"
SENSITIVE_FIELD_NAMES = frozenset(
    {
        "cookie",
        "cookies",
        "password",
        "payload",
        "session_payload_base64",
        "secret",
        "secret_encrypted",
        "token",
    },
)


def redact_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    redacted: list[dict[str, Any]] = []
    for error in errors:
        safe_error = dict(error)
        location = safe_error.get("loc", ())
        if any(str(item).lower() in SENSITIVE_FIELD_NAMES for item in location):
            if "input" in safe_error:
                safe_error["input"] = REDACTED_VALUE
            safe_error.pop("ctx", None)
        redacted.append(safe_error)
    return redacted
