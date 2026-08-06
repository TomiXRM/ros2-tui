"""Flatten a ROS message type into form fields via rosidl introspection."""

from __future__ import annotations

from typing import NamedTuple


class Field(NamedTuple):
    path: str  # e.g. "pose.position.x"
    type_str: str  # e.g. "float64", "sequence<int32>"
    default: str  # prefill text for the input


def flatten_fields(msg, prefix: str = "") -> list[Field]:
    """Recurse into nested messages; arrays and primitives are leaves."""
    fields: list[Field] = []
    for name, type_str in msg.get_fields_and_field_types().items():
        value = getattr(msg, name)
        if hasattr(value, "get_fields_and_field_types"):
            fields.extend(flatten_fields(value, f"{prefix}{name}."))
        else:
            fields.append(Field(f"{prefix}{name}", type_str, _default_text(value)))
    return fields


def _default_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return ""
    if hasattr(value, "tolist"):  # numpy array (fixed-size numeric arrays)
        return str(value.tolist())
    return str(value)
