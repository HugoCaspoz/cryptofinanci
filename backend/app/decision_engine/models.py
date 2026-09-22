from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256
import json

from app.game_state_engine.models import GameState, PlayerState
from app.opponent_model.decision import StrategyInput
from app.poker_engine.models import PokerConfig
from app.poker_engine.ranges import expand_range
from app.strategy_engine.engine import StrategyRequest
from app.strategy_engine.ev import VERSION as EV_VERSION
from app.strategy_engine.models import StrategyConfig
from app.tournament_context.models import TournamentContext


def encode(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Unsupported snapshot value: {type(value)}")


def tuples(value):
    return tuple(tuples(v) for v in value) if isinstance(value, list) else value


@dataclass(frozen=True)
class DecisionSnapshot:
    # JSON is an immutable value, not a frozen wrapper around mutable dicts/lists.
    id: str
    payload_json: str

    @classmethod
    def create(cls, request, *, mode, decision_key, actions, history_complete, evidence, opponents, preflop_config):
        payload = {"schema_version": 1, "ev_model_version": EV_VERSION, "mode": mode, "decision_key": decision_key,
            "scope_id": request.state.scope_id, "hand_id": request.state.hand_id,
            "hero_seat": request.poker.hero_seat, "frame_id": request.frame_id,
            "timestamp": request.timestamp, "source_event_sequence": request.sequence,
            "event_sequence": request.sequence + 1,
            "request": asdict(request), "actions": actions, "history_complete": history_complete,
            "field_evidence": {k: asdict(v) for k, v in evidence.items()},
            "opponents": opponents, "preflop_config": preflop_config,
            "strategy_input_available": request.decision is not None,
            "range_storage": "full_weighted_combos" if request.decision else "configured_priors_only",
            "configured_opponent_ranges": [{"seat": p.seat, "expression": p.range,
                "combos": expand_range(p.range)} for p in request.poker.opponents]}
        frozen = json.dumps(payload, default=encode, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return cls(sha256(frozen.encode()).hexdigest(), frozen)

    def payload(self):
        return json.loads(self.payload_json)

    def record(self):
        return self.payload() | {"id": self.id}

    def request(self):
        payload = self.payload()["request"]
        raw = payload["state"]
        raw["players"] = tuple(PlayerState(**p) for p in raw["players"])
        raw["board"], raw["hero_cards"] = tuple(raw["board"]), tuple(raw["hero_cards"])
        state = GameState(**raw)
        decision = payload["decision"]
        if decision:
            for key in ("board", "seats", "live", "pending", "counts", "neutral_pools", "exploit_pools"):
                decision[key] = tuples(decision[key])
            decision["bets_bb"] = tuple((seat, Decimal(bet)) for seat, bet in decision["bets_bb"])
            for key in ("high_bb", "increment_bb"):
                decision[key] = Decimal(decision[key])
            if decision["tournament"]:
                decision["tournament"] = TournamentContext(**decision["tournament"])
            decision = StrategyInput(**decision)
        return StrategyRequest(state, PokerConfig(**payload["poker"]), StrategyConfig(**payload["config"]),
            decision, payload["preflop"], payload["frame_id"], payload["timestamp"], payload["sequence"], self.id)

    def summary(self):
        data = self.payload()
        return {k: data[k] for k in ("hand_id", "hero_seat", "frame_id", "timestamp", "event_sequence",
                                    "history_complete", "strategy_input_available")} | {
            "id": self.id, "street": data["request"]["state"]["street"], "action_count": len(data["actions"])}
