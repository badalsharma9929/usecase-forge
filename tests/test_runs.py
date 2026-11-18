"""The web run lifecycle: one step per message, idempotent, failure handling, quotas."""

import pytest

from usecase_forge.demo import demo_dependencies
from usecase_forge.keyvault import KeyVault
from usecase_forge.runs import (
    InputError,
    QuotaExceeded,
    RunService,
    TransientError,
    classify,
    validate_url,
)
from usecase_forge.store import MemoryRunStore
from usecase_forge.tools.web import ScrapeError


def make_service(deps_factory=None, daily_limit=3, server_key=True, vault=True):
    return RunService(
        store=MemoryRunStore(),
        vault=KeyVault.ephemeral() if vault else None,
        deps_factory=deps_factory or (lambda key: demo_dependencies(key, delay=0)),
        server_key_available=server_key,
        daily_limit=daily_limit,
    )


def drain(service, message):
    steps = []
    while message:
        steps.append(message["step"])
        message = service.execute(message)
    return steps


def test_full_run_executes_one_step_per_message_with_revision_loop():
    service = make_service()
    snap, message = service.create("byjus.com", [], None)
    steps = drain(service, message)

    assert steps == ["researcher", "strategist", "critic", "strategist", "critic", "dataset_scout", "reporter"]
    run = service.get(snap["id"])
    assert run["status"] == "succeeded"
    assert run["scores"] == [5, 8]
    assert run["url"] == "https://byjus.com"
    assert len(run["results"]) == 4
    assert run["report"].startswith("# GenAI & ML Use Cases for Acme Learning")


def test_duplicate_delivery_is_ignored():
    service = make_service()
    _, message = service.create("https://byjus.com", [], None)
    follow = service.execute(message)
    assert follow["step"] == "strategist"
    assert service.execute(message) is None  # same message again: stale, skipped
    assert service.get(message["run_id"])["steps_done"] == ["researcher"]


def test_permanent_failure_is_recorded_with_friendly_message():
    def broken(_key):
        deps = demo_dependencies(delay=0)
        deps.fetch_page = lambda url: (_ for _ in ()).throw(ScrapeError("blocked by robots"))
        return deps

    service = make_service(broken)
    snap, message = service.create("https://example.com", [], None)
    assert service.execute(message) is None
    run = service.get(snap["id"])
    assert run["status"] == "failed"
    assert "Couldn't read the website" in run["error"]


def test_transient_failure_raises_for_retry_then_gives_up():
    def busy(_key):
        raise RuntimeError("503 UNAVAILABLE model overloaded")

    service = make_service(busy)
    snap, message = service.create("https://example.com", [], None)
    with pytest.raises(TransientError):
        service.execute(message, attempt=1)
    run = service.get(snap["id"])
    assert run["status"] == "running" and "busy" in run["notice"]

    assert service.execute(message, attempt=5) is None
    assert service.get(snap["id"])["status"] == "failed"


def test_daily_quota_applies_only_to_shared_key():
    service = make_service(daily_limit=1)
    service.create("https://a.com", [], None)
    assert service.runs_left_today() == 0
    with pytest.raises(QuotaExceeded):
        service.create("https://b.com", [], None)
    snap, message = service.create("https://b.com", [], "AIza" + "x" * 35)  # own key: allowed
    assert snap["key_source"] == "own"


def test_own_key_is_encrypted_in_message_and_never_stored():
    seen = []
    service = make_service(lambda key: seen.append(key) or demo_dependencies(key, delay=0))
    key = "AIza" + "k" * 35
    snap, message = service.create("https://a.com", [], key)
    assert key not in str(message) and key not in str(snap)
    follow = service.execute(message)
    assert seen == [key]
    assert follow["key"] == message["key"]  # carried forward, still sealed
    assert key not in str(service.store._objects)


def test_public_view_hides_internal_fields():
    service = make_service()
    snap, message = service.create("https://a.com", [], "AIza" + "k" * 35)
    view = service.get(snap["id"])
    assert "key" not in view and "state" not in view


@pytest.mark.parametrize("url", ["not a url", "http://localhost:8000", "http://10.0.0.1", "http://192.168.1.4/x",
                                  "ftp://example.com", "http://[::1]/", "http://intranet.local"])
def test_rejects_unsafe_or_invalid_urls(url):
    with pytest.raises(InputError):
        validate_url(url)


def test_normalises_bare_domain():
    assert validate_url("  zomato.com ") == "https://zomato.com"


def test_get_rejects_malformed_ids():
    assert make_service().get("../../etc/passwd") is None


@pytest.mark.parametrize("text,transient", [
    ("429 RESOURCE_EXHAUSTED ... GenerateRequestsPerDayPerProjectPerModel-FreeTier", False),
    ("429 RESOURCE_EXHAUSTED per minute", True),
    ("503 UNAVAILABLE high demand", True),
    ("400 API_KEY_INVALID", False),
])
def test_error_classification(text, transient):
    assert classify(RuntimeError(text))[0] is transient
