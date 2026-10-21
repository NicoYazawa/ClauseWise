"""Schema base class: unified camelCase aliases + ISO time output (YYYY-MM-DDTHH:MM:SS, matches the frontend)."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


def _fmt_dt(v: datetime | None) -> str | None:
    if v is None:
        return None
    return v.strftime("%Y-%m-%dT%H:%M:%S")


def _fmt_date(v: date | None) -> str | None:
    if v is None:
        return None
    return v.strftime("%Y-%m-%d")


class CamelModel(BaseModel):
    """Outputs camelCase (aligned with frontend TS types); accepts both snake_case / camelCase on input."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        ser_json_by_alias=True,
    )


def serialize_dt(v: datetime | None) -> str | None:
    return _fmt_dt(v)


def serialize_date(v: date | None) -> str | None:
    return _fmt_date(v)
