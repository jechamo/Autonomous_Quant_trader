import json
from typing import Any

import httpx
import pytest
from aqt.data import generate_ohlcv
from aqt.persistence import NullStore, PersistenceError, SupabaseStore
from aqt.research import StudyConfig, run_study


@pytest.fixture(scope="module")
def study():  # type: ignore[no-untyped-def]
    data = {"SAN.MC": generate_ohlcv(900, seed=2), "TINY": generate_ohlcv(50, seed=3)}
    return run_study(data, ["breakout"], StudyConfig(monte_carlo_sims=50, name="t"))


class FakePostgrest:
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.fail_on = fail_on
        self.versions: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        table = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, table, body))
        assert request.headers["apikey"] == "secret-key"
        if table == self.fail_on:
            return httpx.Response(400, text="bad row")
        if request.method == "GET":
            if "config_hash" in str(request.url):
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=self.versions)
        if request.method == "PATCH":
            return httpx.Response(204)
        return httpx.Response(201, json=[{"id": f"{table}-1", **(body or {})}])


def _store(fake: FakePostgrest) -> SupabaseStore:
    client = SupabaseStore.make_client(
        "https://x.supabase.co", "secret-key", transport=httpx.MockTransport(fake)
    )
    return SupabaseStore(client)


def test_persist_study_writes_expected_rows(study) -> None:  # type: ignore[no-untyped-def]
    fake = FakePostgrest()
    exp_id = _store(fake).persist_study(study, ["SAN.MC", "TINY"])
    assert exp_id == "experiments-1"
    tables = [(m, t) for m, t, _ in fake.calls]
    assert tables[0] == ("POST", "experiments")
    assert tables[-1] == ("PATCH", "experiments")
    assert tables.count(("POST", "backtests")) == 2  # IS + OOS for the one valid pair
    assert ("POST", "walk_forward_runs") in tables
    exp = fake.calls[0][2]
    assert exp["n_hypotheses"] == study.n_hypotheses and exp["status"] == "running"
    backtests = [b for m, t, b in fake.calls if t == "backtests"]
    assert {b["sample"] for b in backtests} == {"in_sample", "out_of_sample"}
    version = next(b for m, t, b in fake.calls if t == "strategy_versions" and m == "POST")
    assert version["version"] == 1
    assert fake.calls[-1][2]["status"] == "completed"


def test_failure_marks_experiment_failed(study) -> None:  # type: ignore[no-untyped-def]
    fake = FakePostgrest(fail_on="backtests")
    with pytest.raises(PersistenceError):
        _store(fake).persist_study(study, ["SAN.MC"])
    assert fake.calls[-1][0] == "PATCH" and fake.calls[-1][2]["status"] == "failed"


def test_from_env_and_repr() -> None:
    with pytest.raises(PersistenceError):
        SupabaseStore.from_env({})
    store = SupabaseStore.from_env(
        {"SUPABASE_URL": "https://x.supabase.co/", "SUPABASE_SERVICE_ROLE_KEY": "k3y"}
    )
    assert "k3y" not in repr(store)
    assert NullStore().persist_study(None, []) is None  # type: ignore[arg-type]
