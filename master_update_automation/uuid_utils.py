"""UUID normalisation, formatting, and validation."""

from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

UUID_CORE_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _extract_uuid_core(value: str) -> Optional[str]:
    """Strip whitespace and wrapping braces, then return the UUID core if valid."""
    text = value.strip()
    if not text:
        return None
    while len(text) >= 2 and text[0] == "{" and text[-1] == "}":
        text = text[1:-1].strip()
    if UUID_CORE_PATTERN.match(text):
        return text.lower()
    return None


def is_valid_uuid(value: str) -> bool:
    """Return True if the string is a standard UUID, with or without braces."""
    if not value or not isinstance(value, str):
        return False
    return _extract_uuid_core(value) is not None


def normalise_uuid(value: Optional[str]) -> str:
    """
    Normalise a UUID to {xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}.

    Empty/None stays empty. Valid UUIDs get exactly one brace pair.
    Invalid non-empty values are returned as-is (caller validates).
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return ""
    core = _extract_uuid_core(value)
    if core:
        return f"{{{core}}}"
    logger.warning("Invalid UUID value encountered: '%s'", value)
    return value


def strip_uuid_braces(value: Optional[str]) -> str:
    """Remove braces from a UUID for comparison."""
    if not value or not isinstance(value, str):
        return ""
    core = _extract_uuid_core(value)
    if core:
        return core
    return value.strip()


def validate_uuid_field(field_name: str, value: Optional[str]) -> Optional[str]:
    """Return an error message if a non-empty UUID field is invalid."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    if not value.strip():
        return None
    if _extract_uuid_core(value) is None:
        return f"Field '{field_name}' contains invalid UUID: '{value}'"
    return None


def uuid_output_is_canonical(value: str) -> bool:
    """True when value is a valid UUID wrapped in exactly one brace pair."""
    if not value or not isinstance(value, str):
        return False
    text = value.strip()
    if not (text.startswith("{") and text.endswith("}") and not text.startswith("{{")):
        return False
    inner = text[1:-1]
    return bool(UUID_CORE_PATTERN.match(inner))


def split_valid_uuid(value: Optional[str]) -> Tuple[bool, str]:
    """Return (is_valid, canonical_or_original)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return True, ""
    canonical = normalise_uuid(value)
    return is_valid_uuid(canonical if canonical.startswith("{") else value), canonical
