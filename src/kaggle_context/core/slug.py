"""Turn whatever the user pastes into a competition slug."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
_PATH = re.compile(r"^/(?:competitions|c)/([^/?#]+)")


def parse_competition(value: str) -> str:
    """Return the competition slug from a URL or a bare slug.

    Accepts ``https://www.kaggle.com/competitions/<slug>/...``, the short ``/c/<slug>``
    form, URLs without a scheme, and plain slugs. Raises ``ValueError`` otherwise.
    """
    text = value.strip().strip("'\"")
    if not text:
        raise ValueError("Enter a Kaggle competition URL or slug.")

    if "kaggle.com" in text or text.startswith(("http://", "https://", "/")):
        if "://" not in text and not text.startswith("/"):
            text = "https://" + text
        parsed = urlparse(text)
        if parsed.netloc and not parsed.netloc.endswith("kaggle.com"):
            raise ValueError(f"Not a kaggle.com URL: {value!r}")
        match = _PATH.match(parsed.path)
        if not match:
            raise ValueError(
                "That URL is not a competition page. "
                "Expected https://www.kaggle.com/competitions/<name>"
            )
        text = match.group(1)

    slug = text.lower()
    if not _SLUG.match(slug):
        raise ValueError(f"Not a valid competition name: {value!r}")
    return slug


def competition_url(slug: str, *parts: str) -> str:
    return "/".join(["https://www.kaggle.com/competitions", slug, *parts])
