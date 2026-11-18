"""Run lifecycle for the web app: create a run, execute one step per queue message,
and expose a safe public view.

A run is a sequence of immutable snapshots. Message ``seq`` must match the latest
snapshot's ``seq``; anything else is a duplicate or stale delivery and is ignored,
which makes every step idempotent under at-least-once queue delivery.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

from usecase_forge.graph import FIRST_STEP, MissingApiKeyError, initial_state, run_step
from usecase_forge.keyvault import KeyVault
from usecase_forge.state import Dependencies, dump_state, load_state
from usecase_forge.store import RunStore
from usecase_forge.tools.web import ScrapeError

log = logging.getLogger(__name__)

RUN_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_TRANSIENT_ATTEMPTS = 5
TERMINAL = {"succeeded", "failed"}


# --- errors ---------------------------------------------------------------

class InputError(ValueError):
    """The request is invalid; message is safe to show the user."""


class QuotaExceeded(RuntimeError):
    pass


class TransientError(RuntimeError):
    """A step failed for a reason that may pass (model overloaded); retry later."""

    def __init__(self, message: str, delay: int):
        super().__init__(message)
        self.delay = delay


def classify(exc: Exception) -> tuple[bool, str]:
    """Return (is_transient, user-facing message)."""
    text = str(exc)
    if isinstance(exc, ScrapeError):
        return False, f"Couldn't read the website. {text}"
    if isinstance(exc, MissingApiKeyError):
        return False, str(exc)
    if "API_KEY_INVALID" in text or "API key not valid" in text:
        return False, "Gemini rejected the API key. Check that it is correct and active."
    if "RESOURCE_EXHAUSTED" in text and "PerDay" in text:
        return False, ("The Gemini free-tier daily quota is used up. "
                       "Try again tomorrow, or run it with your own Gemini API key.")
    if any(s in text for s in ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "503", "DEADLINE_EXCEEDED", "429")):
        return True, "Gemini is busy right now. Retrying automatically..."
    return False, f"The pipeline stopped unexpectedly ({type(exc).__name__})."


# --- validation ------------------------------------------------------------

def validate_url(raw: str) -> str:
    url = raw.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or "." not in host or len(url) > 500:
        raise InputError(f"'{raw}' is not a valid website address.")
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise InputError("Only public websites can be analysed.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None  # a hostname, not an IP literal
    if ip is not None and not ip.is_global:
        raise InputError("Only public websites can be analysed.")
    return url


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- service ---------------------------------------------------------------

@dataclass
class RunService:
    store: RunStore
    vault: KeyVault | None
    deps_factory: Callable[[str | None], Dependencies]  # api_key -> dependencies
    server_key_available: bool
    daily_limit: int

    # Creating -------------------------------------------------------------

    def runs_left_today(self) -> int | None:
        if not self.server_key_available:
            return 0
        return max(0, self.daily_limit - self.store.server_runs_today())

    def create(self, url: str, extra_urls: list[str], api_key: str | None) -> tuple[dict, dict]:
        """Validate, persist the first snapshot, and return (snapshot, first queue message)."""
        url = validate_url(url)
        extras = [validate_url(u) for u in extra_urls if u.strip()]
        if len(extras) > 3:
            raise InputError("Add at most 3 extra pages.")
        api_key = (api_key or "").strip() or None

        if api_key:
            if self.vault is None:
                raise InputError("Using your own key is not enabled on this server.")
            if not re.fullmatch(r"[A-Za-z0-9_\-]{20,200}", api_key):
                raise InputError("That doesn't look like a Gemini API key.")
        elif not self.server_key_available:
            raise InputError("This server has no shared Gemini key. Please use your own key.")
        elif self.runs_left_today() == 0:
            raise QuotaExceeded(
                f"The shared demo key has reached today's limit of {self.daily_limit} runs. "
                "Add your own free Gemini key to keep going."
            )

        run_id = uuid.uuid4().hex
        snapshot = {
            "id": run_id,
            "seq": 0,
            "rev": 0,
            "status": "queued",
            "step": FIRST_STEP,
            "steps_done": [],
            "key_source": "own" if api_key else "server",
            "created_at": _now(),
            "updated_at": _now(),
            "notice": None,
            "error": None,
            "state": dump_state(initial_state(url, extras)),
        }
        self.store.save(snapshot)
        if not api_key:
            self.store.record_server_run(run_id)
        message = {"run_id": run_id, "step": FIRST_STEP, "seq": 0}
        if api_key:
            message["key"] = self.vault.seal(api_key)
        return snapshot, message

    # Executing ------------------------------------------------------------

    def execute(self, message: dict, attempt: int = 1) -> dict | None:
        """Run one step. Returns the next queue message, or None when there is none.

        Raises TransientError when the step should be retried later.
        """
        run_id, step, seq = message["run_id"], message["step"], message["seq"]
        snap = self.store.latest(run_id)
        if snap is None or snap["seq"] != seq or snap["status"] in TERMINAL or snap["step"] != step:
            log.info("Skipping stale delivery %s/%s seq=%s", run_id, step, seq)
            return None

        api_key = self.vault.open(message["key"]) if message.get("key") and self.vault else None
        if snap["status"] == "queued":
            snap = self._save(snap, status="running")

        try:
            deps = self.deps_factory(api_key)
            new_state, nxt = run_step(step, load_state(snap["state"]), deps)
        except Exception as exc:  # noqa: BLE001 - every failure must end up in the run record
            transient, msg = classify(exc)
            log.warning("Step %s of run %s failed (attempt %s): %r", step, run_id, attempt, exc)
            if transient and attempt < MAX_TRANSIENT_ATTEMPTS:
                self._save(snap, notice=msg)
                raise TransientError(msg, delay=min(300, 15 * 2 ** (attempt - 1))) from exc
            self._save(snap, status="failed", error=msg, notice=None)
            return None

        done = self._save(
            snap,
            new_seq=True,
            state=dump_state(new_state),
            steps_done=[*snap["steps_done"], step],
            step=nxt,
            status="running" if nxt else "succeeded",
            notice=None,
        )
        if nxt is None:
            return None
        follow = {"run_id": run_id, "step": nxt, "seq": done["seq"]}
        if message.get("key"):
            follow["key"] = message["key"]
        return follow

    def _save(self, snap: dict, new_seq: bool = False, **changes) -> dict:
        updated = {**snap, **changes, "updated_at": _now()}
        if new_seq:
            updated["seq"], updated["rev"] = snap["seq"] + 1, 0
        else:
            updated["rev"] = snap["rev"] + 1
        self.store.save(updated)
        return updated

    # Reading --------------------------------------------------------------

    def get(self, run_id: str) -> dict | None:
        if not RUN_ID.match(run_id):
            return None
        snap = self.store.latest(run_id)
        return public_view(snap) if snap else None


def public_view(snap: dict) -> dict:
    """What the browser may see. Never includes keys or raw page text."""
    state = snap["state"]
    critique = state.get("critique")
    return {
        "id": snap["id"],
        "status": snap["status"],
        "step": snap["step"],
        "steps_done": snap["steps_done"],
        "key_source": snap["key_source"],
        "created_at": snap["created_at"],
        "updated_at": snap["updated_at"],
        "notice": snap.get("notice"),
        "error": snap.get("error"),
        "url": state.get("url"),
        "profile": state.get("profile"),
        "scores": state.get("scores", []),
        "critique": critique,
        "results": state.get("results"),
        "sources": state.get("sources"),
        "report": state.get("report"),
        "log": state.get("log", []),
    }
