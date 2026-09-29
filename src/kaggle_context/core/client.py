"""Thin wrapper over the official Kaggle API.

Why a wrapper:

* ``import kaggle`` authenticates at import time and the API prints to stdout
  (e.g. ``Next Page Token = ...``). Stray stdout corrupts both the TUI and the MCP
  stdio protocol, so all Kaggle output is silenced here.
* A missing credential makes the SDK call ``exit(1)``; we turn that into ``AuthError``.
* Transient failures (429 / 5xx / connection errors) are retried with backoff.
* Every method returns plain dicts, so tests can replay recorded JSON fixtures.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

RETRY_STATUSES = {429, 500, 502, 503, 504}


class KaggleError(Exception):
    """Base class for errors talking to Kaggle."""


class AuthError(KaggleError):
    pass


class NotFoundError(KaggleError):
    pass


class ForbiddenError(KaggleError):
    pass


class KaggleSource(Protocol):
    """What the fetch pipeline needs from Kaggle. Implemented by ``KaggleClient`` and test fakes."""

    def competition(self, slug: str) -> dict[str, Any] | None: ...
    def pages(self, slug: str) -> list[dict[str, Any]]: ...
    def files(self, slug: str) -> list[dict[str, Any]]: ...
    def topics(self, slug: str, sort_by: str, page: int) -> dict[str, Any]: ...
    def topic(self, topic_id: int, page_size: int) -> dict[str, Any]: ...
    def kernels(self, slug: str, page_size: int) -> list[dict[str, Any]]: ...
    def pull_kernel(self, ref: str, dest: Path) -> dict[str, Any]: ...
    def leaderboard(self, slug: str, page_size: int) -> list[dict[str, Any]]: ...


def _quiet_print(*args: Any, **kwargs: Any) -> None:
    log.debug(" ".join(str(a) for a in args))


def _load_api() -> Any:
    """Import the Kaggle SDK with its stdout chatter silenced."""
    with contextlib.redirect_stdout(io.StringIO()):
        # `kaggle/__init__.py` rebinds `kaggle.api` to an instance, so fetch the module
        # object from sys.modules rather than via attribute access.
        from kaggle.api.kaggle_api_extended import KaggleApi
    ext = sys.modules[KaggleApi.__module__]

    # The SDK uses bare print(); shadowing it at module level is thread-safe,
    # unlike swapping sys.stdout while worker threads run.
    ext.print = _quiet_print  # type: ignore[attr-defined]
    return KaggleApi


def credentials_present() -> bool:
    """Cheap check for any credential source, without a network call."""
    if os.environ.get("KAGGLE_API_TOKEN") or (
        os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY")
    ):
        return True
    config_dir = Path(os.environ.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle"))
    return any(
        (config_dir / name).exists()
        for name in ("access_token", "access_token.txt", "kaggle.json", "credentials.json")
    )


def save_access_token(token: str) -> Path:
    """Store a pasted API token where the Kaggle SDK looks for it (``~/.kaggle/access_token``)."""
    token = token.strip()
    if not token:
        raise ValueError("Token is empty.")
    config_dir = Path(os.environ.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle"))
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = config_dir / "access_token"
    path.write_text(token + "\n")
    path.chmod(0o600)
    return path


class KaggleClient:
    def __init__(self, retries: int = 4, backoff: float = 1.5) -> None:
        self._api: Any = None
        self._retries = retries
        self._backoff = backoff

    # -- plumbing -----------------------------------------------------------------

    @property
    def api(self) -> Any:
        if self._api is None:
            api_cls = _load_api()
            api = api_cls()
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    api.authenticate()
            except SystemExit as exc:
                raise AuthError(
                    "No Kaggle credentials found. Run `kctx` and pick 'Log in', "
                    "or create a token at https://www.kaggle.com/settings/api"
                ) from exc
            self._api = api
        return self._api

    def _call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        import requests

        delay = self._backoff
        for attempt in range(self._retries + 1):
            try:
                return fn(*args, **kwargs)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in RETRY_STATUSES and attempt < self._retries:
                    log.debug("Kaggle returned %s, retrying in %.1fs", status, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                if status == 404:
                    raise NotFoundError("Not found on Kaggle.") from exc
                if status in (401, 403):
                    raise ForbiddenError(
                        "Kaggle refused access. For data files you must accept the "
                        "competition rules first."
                    ) from exc
                raise KaggleError(str(exc)) from exc
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt < self._retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise KaggleError(f"Network error talking to Kaggle: {exc}") from exc
        raise AssertionError("unreachable")

    # -- account ------------------------------------------------------------------

    def whoami(self) -> str | None:
        return self.api.config_values.get("username")

    def login_with_browser(self) -> None:
        """Run Kaggle's OAuth browser login. Prints to the terminal; call it outside the TUI."""
        api_cls = _load_api()
        api_cls().auth_login_cli()
        self._api = None

    # -- competitions -------------------------------------------------------------

    def search_competitions(
        self, query: str = "", group: str | None = None
    ) -> list[dict[str, Any]]:
        resp = self._call(self.api.competitions_list, search=query or None, group=group)
        comps = getattr(resp, "competitions", resp) or []
        return [c.to_dict() for c in comps]

    def competition(self, slug: str) -> dict[str, Any] | None:
        for query in (slug, slug.replace("-", " ")):
            for comp in self.search_competitions(query):
                if _slug_of(comp) == slug:
                    return comp
        return None

    def has_entered(self, slug: str) -> bool:
        """True if the user has joined the competition (i.e. accepted its rules)."""
        return any(_slug_of(c) == slug for c in self.search_competitions(slug, group="entered"))

    def pages(self, slug: str) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self._call(self.api.competition_list_pages, slug) or []]

    def files(self, slug: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        token = None
        while True:
            resp = self._call(
                self.api.competition_list_files, slug, page_token=token, page_size=200
            )
            out.extend(f.to_dict() for f in resp.files)
            token = resp.next_page_token
            if not token:
                return out

    def topics(self, slug: str, sort_by: str = "top", page: int = 1) -> dict[str, Any]:
        resp = self._call(self.api.competition_list_topics, slug, sort_by=sort_by, page=page)
        return resp.to_dict()

    def topic(self, topic_id: int, page_size: int = 200) -> dict[str, Any]:
        topic, comments, _token = self._call(
            self.api.forums_topic_show, int(topic_id), page_size=page_size
        )
        return {"topic": topic.to_dict(), "comments": [c.to_dict() for c in comments or []]}

    def kernels(self, slug: str, page_size: int = 20) -> list[dict[str, Any]]:
        resp = self._call(
            self.api.kernels_list, competition=slug, sort_by="voteCount", page_size=page_size
        )
        return [k.to_dict() for k in resp or []]

    def pull_kernel(self, ref: str, dest: Path) -> dict[str, Any]:
        """Download a notebook's source into ``dest`` as ``<owner>__<slug>.<ext>``.

        Returns Kaggle's kernel metadata plus ``local_file`` (the saved file name).
        """
        dest.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dest) as tmp:
            self._call(self.api.kernels_pull, ref, path=tmp, metadata=True, quiet=True)
            meta = json.loads((Path(tmp) / "kernel-metadata.json").read_text())
            source = Path(tmp) / meta.get("code_file", "")
            if not source.is_file():
                candidates = [p for p in Path(tmp).iterdir() if p.name != "kernel-metadata.json"]
                if not candidates:
                    raise KaggleError(f"Kaggle returned no source for {ref}")
                source = candidates[0]
            target = dest / (ref.replace("/", "__") + source.suffix)
            shutil.move(source, target)
        meta["local_file"] = target.name
        return meta

    def leaderboard(self, slug: str, page_size: int = 20) -> list[dict[str, Any]]:
        rows = self._call(self.api.competition_leaderboard_view, slug, page_size=page_size)
        return [r.to_dict() for r in rows or []]


def _slug_of(comp: dict[str, Any]) -> str:
    return str(comp.get("ref") or comp.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
