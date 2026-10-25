import asyncio
from dataclasses import replace
from io import BytesIO
import json
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import FeedbackRelease, Mode, Settings
from app.decision_engine.evaluation import DecisionEvaluator
from app.hand_reconstructor.store import HandStore
from app.llm_explainer.facts import build_facts
from app.llm_explainer.provider import OpenAIProvider
from app.llm_explainer.service import ExplanationBusy, ExplanationService
from app.main import create_app
from test_decision_evaluation import spot, observed, link
from test_feedback import client, seed, end_hand


@pytest.fixture
def sample():
    _, _, frozen = spot(True)
    evaluation = DecisionEvaluator().evaluate(frozen, link(frozen, observed(frozen)))
    return frozen.record(), evaluation["strategy_result"], evaluation


class Editor:
    calls = 0
    fail = False

    def plan(self, facts, style):
        self.calls += 1
        if self.fail:
            raise TimeoutError("secret provider details must not reach client")
        return [fact["id"] for fact in facts]


def test_facts_are_grounded_styles_differ_and_snapshot_is_not_mutated(sample):
    record, strategy, evaluation = sample
    original = json.dumps(sample, sort_keys=True)
    simple = build_facts(*sample, "simple")
    advanced = build_facts(*sample, "advanced")
    assert {f["id"] for f in simple} < {f["id"] for f in advanced}
    assert "ranges" in {f["id"] for f in advanced}
    for key in ["context", "baseline_strategy", "exploitative_strategy", "actual_action", "comparison_baseline", "limits"]:
        assert next(f for f in simple if f["id"] == key)["required"]
    assert "state_after" not in json.dumps(advanced)
    assert "nickname" not in json.dumps(advanced)
    assert json.dumps(sample, sort_keys=True) == original


def test_partial_preflop_retains_missing_data_limits(sample):
    record, strategy, _ = sample
    record = json.loads(json.dumps(record))
    record["history_complete"] = False
    record["request"]["state"]["street"] = "preflop"
    facts = build_facts(record, strategy, None, "simple")
    assert {"partial_history", "preflop_limit"} <= {f["id"] for f in facts if f["required"]}


@pytest.mark.parametrize("invalid", ["unknown", "duplicate", "missing_required", "incomplete", "refusal", "free_text", "oversized"])
def test_openai_rejects_unusable_or_ungrounded_plans(sample, invalid):
    facts = build_facts(*sample, "simple")
    plan = [fact["id"] for fact in facts]
    if invalid == "unknown": plan.append("invented_strategy")
    if invalid == "duplicate": plan.append(plan[0])
    if invalid == "missing_required": plan.remove("limits")
    response = {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps({"fact_ids": plan})}]}]}
    if invalid == "incomplete": response["status"] = "incomplete"
    if invalid == "refusal": response["output"][0]["content"] = [{"type": "refusal", "refusal": "no"}]
    if invalid == "free_text": response["output"][0]["content"][0]["text"] = json.dumps({"fact_ids": plan, "advice": "invented"})
    raw = json.dumps(response).encode() if invalid != "oversized" else b"x" * 65537
    provider = OpenAIProvider("secret", "configured-model", transport=lambda *a, **k: BytesIO(raw))
    with pytest.raises(ValueError):
        provider.plan(facts, "simple")


def test_openai_request_has_fixed_endpoint_no_tools_no_storage_or_player_names(sample):
    facts = build_facts(*sample, "advanced")
    def transport(request, timeout):
        assert request.full_url == "https://api.openai.com/v1/responses"
        body = json.loads(request.data)
        assert body["store"] is False
        assert "tools" not in body
        assert "nickname" not in body["input"]
        assert body["text"]["format"]["strict"] is True
        assert body["model"] == "configured-model" and timeout == 12
        return BytesIO(json.dumps({"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps({"fact_ids": [f["id"] for f in facts]})}]}]}).encode())
    assert OpenAIProvider("secret", "configured-model", transport=transport).plan(facts, "advanced")
    assert "secret" not in repr(Settings(mode=Mode.TRAINING, openai_api_key="secret"))


def test_cache_persists_style_and_provider_are_separate_failures_retry(sample, tmp_path):
    async def run():
        store = HandStore(path=tmp_path / "explanations.sqlite")
        store.initialize()
        editor = Editor()
        service = ExplanationService(Settings(mode=Mode.TRAINING, openai_model="test-model"), store, editor)
        checks = []
        async def access(): checks.append(True)
        first = await service.explain(*sample, "simple", access)
        assert first["provider"] == "openai" and not first["cached"]
        assert (await service.explain(*sample, "simple", access))["cached"]
        assert editor.calls == 1
        reopened = HandStore(path=store.path)
        reopened.initialize()
        again = ExplanationService(service.settings, reopened, editor)
        assert (await again.explain(*sample, "simple", access))["cached"]
        editor.fail = True
        fallback = await again.explain(*sample, "advanced", access)
        assert fallback["provider"] == "local" and fallback["fallback_reason"]
        assert "secret" not in json.dumps(fallback)
        editor.fail = False
        assert (await again.explain(*sample, "advanced", access))["provider"] == "openai"
        assert editor.calls == 3
        local = ExplanationService(Settings(mode=Mode.TRAINING), reopened)
        assert (await local.explain(*sample, "simple", access))["provider"] == "local"
        assert len(checks) >= 8
    asyncio.run(run())


def test_access_rechecked_after_provider_and_busy_generation_is_bounded(sample, tmp_path):
    async def run():
        store = HandStore(path=tmp_path / "access.sqlite")
        store.initialize()
        editor = Editor()
        service = ExplanationService(Settings(mode=Mode.TRAINING), store, editor)
        blocked = False
        def plan(facts, style):
            nonlocal blocked
            blocked = True
            return [fact["id"] for fact in facts]
        editor.plan = plan
        async def access():
            if blocked: raise HTTPException(403, "revoked")
        with pytest.raises(HTTPException):
            await service.explain(*sample, "simple", access)
        with store.connection() as db:
            assert db.execute("SELECT COUNT(*) FROM decision_explanations").fetchone()[0] == 0
        blocked = False
        async with service.lock:
            with pytest.raises(ExplanationBusy):
                await service.explain(*sample, "simple", access)
    asyncio.run(run())


def test_explanation_api_obeys_policies_and_new_capture_reblocks_cached_text(client):
    data = seed(client, FeedbackRelease.HAND_FINISHED)
    store, frozen, *_ = data
    url = f"/api/decisions/{frozen.id}/explanation"
    editor = Editor()
    client.app.state.explainer.provider = editor
    assert client.post(url, json={"style": "simple"}).status_code == 403
    assert editor.calls == 0
    end_hand(data)
    assert client.post(url, json={"style": "invalid"}).status_code == 422
    response = client.post(url, json={"style": "simple"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.json()["paragraphs"]
    assert client.post(url, json={"style": "simple"}).json()["cached"]
    capture = client.app.state.capture
    capture.state = "running"
    assert client.post(url, json={"style": "simple"}).status_code == 403
    assert editor.calls == 1
    capture.state = "stopped"
    assert client.post(url, json={"style": "advanced"}).status_code == 200


def test_session_policy_and_cross_mode_reject_explanation(client):
    data = seed(client)
    _, frozen, *_ = data
    end_hand(data)
    url = f"/api/decisions/{frozen.id}/explanation"
    assert client.post(url, json={}).status_code == 403
    data[0].stop_review_capture("scope")
    assert client.post("/api/feedback/sessions/scope/finish", json={"session_finished": True}).status_code == 200
    assert client.post(url, json={}).status_code == 200
    client.app.state.capture.mode = Mode.TRAINING
    assert client.post(url, json={}).status_code == 403
    client.app.state.capture.mode = Mode.LIVE_REAL_MONEY


def test_training_can_explain_saved_strategy_before_action_without_recalculating(tmp_path, monkeypatch):
    from app.strategy_engine.engine import StrategyEngine
    from app.strategy_engine.strategy_service import StrategyService
    from test_decisions import event_for
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "training.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.TRAINING))) as current:
        s, request, frozen = spot()
        store = current.app.state.hand_store
        store.save_decision(frozen.record(), event_for(s, frozen, request))
        url = f"/api/decisions/{frozen.id}/explanation"
        assert current.post(url, json={}).status_code == 409
        strategy = StrategyEngine().analyze(frozen.request())
        _, saved = StrategyService(Mode.TRAINING, lambda: None).record(frozen.request(), strategy)
        store.save_strategy(saved)
        # The endpoint must read the saved result, never run the mathematical engine.
        monkeypatch.setattr(StrategyEngine, "analyze", lambda *a, **k: pytest.fail("Unexpected recalculation"))
        response = current.post(url, json={})
        assert response.status_code == 200
        assert "actual_action" not in {p["fact_id"] for p in response.json()["paragraphs"]}


@pytest.mark.skipif(not os.getenv("HAND_TEST_POSTGRES"), reason="Dedicated PostgreSQL test database required")
def test_postgres_explanation_and_frame_persistence():
    store = HandStore(database_url=os.environ["HAND_TEST_POSTGRES"])
    store.initialize()
    key = uuid4().hex
    result = {"paragraphs": [{"text": "fact", "fact_id": "limits"}]}
    assert store.save_explanation(key, key, result) == result
    assert store.get_explanation(key) == result
    from test_decisions import setup, freeze, event_for
    from app.decision_engine.tracker import DecisionTracker
    s, request = setup()
    request = replace(request, state=replace(request.state, hand_id=key, scope_id=key),
                      decision=replace(request.decision, hand_id=key, scope_id=key))
    frozen = freeze(DecisionTracker(), s, request, events=())
    from app.event_engine.models import PokerEvent
    event = PokerEvent(type="HERO_DECISION_REQUIRED", sequence=frozen.record()["event_sequence"],
        scope_id=key, hand_id=key, frame_id=request.frame_id, timestamp=request.timestamp,
        decision_id=frozen.id, player_id=request.state.current_player, state_after=request.state)
    store.save_decision(frozen.record(), event, b"postgres-frame")
    assert store.get_decision_frame(frozen.id) == b"postgres-frame"
    with pytest.raises(ValueError):
        store.save_decision(frozen.record(), event, b"changed")
    assert store.get_decision_frame(frozen.id) == b"postgres-frame"


def test_incomplete_configuration_uses_local_without_exposing_the_key(sample, tmp_path):
    async def run():
        store = HandStore(path=tmp_path / "config.sqlite")
        store.initialize()
        settings = Settings(mode=Mode.TRAINING, explainer_provider="openai", openai_api_key="private-key", openai_model=None)
        service = ExplanationService(settings, store)
        async def access(): pass
        response = await service.explain(*sample, "simple", access)
        assert response["provider"] == "local" and response["fallback_reason"]
        assert "private-key" not in json.dumps(response)
        assert service.provider is None
    asyncio.run(run())
    with pytest.raises(ValueError):
        Settings(mode=Mode.TRAINING, explainer_provider="arbitrary")
