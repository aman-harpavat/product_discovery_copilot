from __future__ import annotations

from difflib import get_close_matches

_COUNTRY_ALIASES = {
    "au": "au",
    "australia": "au",
    "ca": "ca",
    "canada": "ca",
    "gb": "gb",
    "great britain": "gb",
    "uk": "gb",
    "united kingdom": "gb",
    "in": "in",
    "india": "in",
    "nz": "nz",
    "new zealand": "nz",
    "sg": "sg",
    "singapore": "sg",
    "us": "us",
    "usa": "us",
    "united states": "us",
    "united states of america": "us",
}


def resolve_country_code(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = " ".join(value.strip().lower().replace("-", " ").replace("_", " ").split())
    if not cleaned:
        return None

    if len(cleaned) == 2 and cleaned.isalpha():
        return cleaned

    if cleaned in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[cleaned]

    close_matches = get_close_matches(cleaned, _COUNTRY_ALIASES.keys(), n=1, cutoff=0.78)
    if close_matches:
        return _COUNTRY_ALIASES[close_matches[0]]

    raise ValueError(
        "country must be a supported country name or 2-letter code, for example 'India', 'US', or 'gb'"
    )
