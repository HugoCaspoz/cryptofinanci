import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Callable
from uuid import uuid4
from dataclasses import asdict, replace

from app.game_state_engine import GameStateEngine
from app.pipeline_engine.pipeline import FramePipeline
from app.pipeline_engine.processor import FrameProcessor, ProcessedFrame
from app.poker_engine.service import PokerService
from app.strategy_engine.service import PreflopService
from app.strategy_engine.strategy_service import StrategyService
from app.opponent_model.service import OpponentService
from app.decision_engine.service import DecisionService
from app.decision_engine.evaluation_service import EvaluationService
from app.strategy_engine.engine import StrategyRequest
from app.config import FeedbackRelease, Mode

from .screen_source import ScreenCaptureSource
from .source import SourceError, VideoSource

logger = logging.getLogger(__name__)


class CaptureConflict(ValueError):
    pass


class CaptureEngine:
    """Source lifecycle and API state; FramePipeline owns concurrent processing."""

    def __init__(self, queue_size: int = 2,
                 processor_factory: Callable[[], FrameProcessor] = FrameProcessor, hand_store=None, mode=None,
                 on_update=None, feedback_release=FeedbackRelease.SESSION_FINISHED):
        if not 1 <= queue_size <= 8:
            raise ValueError("La capacidad de la cola debe estar entre 1 y 8.")
        self.queue_size = queue_size
        self.processor_factory = processor_factory
        self.hand_store, self.mode = hand_store, mode
        self.on_update = on_update
        self.server_id = str(uuid4())
        self.revision = 0
        self.storage_error = None
        self.pending_events = []
        self._control = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.source: VideoSource | None = None
        self.pipeline: FramePipeline | None = None
        self.observation_state = GameStateEngine()
        self.capture_id: str | None = None
        self.state = "idle"
        self.error: str | None = None
        self.preview: tuple[dict, bytes] | None = None
        self._temp = tempfile.TemporaryDirectory(prefix="zeros-capture-")
        self.upload_dir = Path(self._temp.name)
        self.poker = PokerService(mode, self._notify)
        self.preflop = PreflopService(mode, hand_store)
        self.opponents = OpponentService(self.observation_state.current_state.scope_id, mode, hand_store)
        self.strategy = StrategyService(mode, self._notify, hand_store)
        self.decisions = DecisionService(mode, hand_store, self._decision_saved)
        self.evaluations = EvaluationService(mode, hand_store, self._notify)
        self.feedback_release = FeedbackRelease(feedback_release)
        self.feedback_revision = 0
        self.session_release = None

    def review_blocked(self):
        game = self.observation_state
        return self.mode == Mode.LIVE_REAL_MONEY and (game.current_state.hand_status == "active"
            or self.state == "running" and game.hands.finished_count == 0)

    def feedback_status(self):
        return {"next_release": self.feedback_release, "session_release": self.session_release,
                "revision": self.feedback_revision, "review_blocked": self.review_blocked()}

    def _decision_saved(self):
        self._analyze()
        self._notify()

    def status(self) -> dict:
        observation = self.observation_state.last_observation
        return {
            "server_id": self.server_id,
            "revision": self.revision,
            "capture_id": self.capture_id,
            "state": self.state,
            "source": self.source.kind if self.source else None,
            "name": self.source.name if self.source else None,
            "capture_fps": self.source.capture_fps if self.source else 5,
            "duration": self.source.duration if self.source else None,
            "error": self.error,
            "frame": self.preview[0] if self.preview else None,
            "pipeline": self.pipeline.snapshot() if self.pipeline else None,
            "observation_state": self.observation_state.snapshot(),
            "poker": self.poker.snapshot(),
            "opponents": self.opponents.snapshot(),
            "strategy": self.strategy.snapshot(self.state == "running"),
            "decisions": self.decisions.snapshot(self.observation_state.decisions),
            "evaluations": self.evaluations.snapshot(),
            "feedback": self.feedback_status(),
            "preflop": self.preflop.snapshot(self.observation_state.current_state, self.observation_state.evidence,
                observation.source_timestamp if observation else None,
                self.observation_state.event_engine.replay.sequence, self.state == "running"),
            "hand_storage": {"kind": self.hand_store.kind if self.hand_store else "disabled",
                             "error": self.storage_error},
        }

    def _notify(self):
        self.revision += 1
        if self.on_update:
            self.on_update(self.status())

    async def _publish(self, result: ProcessedFrame) -> None:
        await self.decisions.flush()  # Never advance the frame while a frozen decision is unsaved.
        sequence = self.observation_state.event_engine.replay.sequence
        was_blocked = self.review_blocked()
        self.observation_state.accept(result.observation)
        # Revoke an open review before awaiting disk/OCR consumers for the new hand.
        if not was_blocked and self.review_blocked():
            self._notify()
        self.pending_events.extend(e for e in self.observation_state.event_engine.events if e.sequence > sequence)
        hands = self.observation_state.hands
        if hands.active and self.pending_events:
            hands.pending_records.append({**hands.active, "state": asdict(hands.last_state)})
        await self._save_hands()
        async with self.opponents.lock:
            await self._opponents_locked()
        async with self.preflop.lock:
            await self._preflop_locked()
        self.preview = result.metadata, result.jpeg
        self._analyze()
        self._notify()

    async def _preflop_locked(self):
        game = self.observation_state
        observation = game.last_observation
        await self.preflop.update(game.current_state, game.evidence, tuple(game.event_engine.events),
                                  game.event_engine.replay.sequence,
                                  observation.frame_id if observation else None,
                                  observation.source_timestamp if observation else None)

    async def _opponents_locked(self):
        game = self.observation_state
        observation = game.last_observation
        await self.opponents.update(tuple(game.event_engine.events), game.event_engine.replay.sequence,
            game.current_state, observation.frame_id if observation else None,
            observation.source_timestamp if observation else None)

    def _analyze(self):
        game = self.observation_state
        observation = game.last_observation
        frame_id = observation.frame_id if observation else None
        timestamp = observation.source_timestamp if observation else None
        sequence = game.event_engine.replay.sequence
        # Opponent inputs only when their model has consumed exactly the events of this state.
        synced = (not self.opponents.storage_error and self.opponents.pending is None
                  and self.opponents.model.cursor == sequence)
        adaptive = None
        if self.poker.config.range_source == "adaptive" and synced:
            adaptive = self.opponents.model.adaptive_input(game.current_state)
        self.poker.submit(game.current_state, game.evidence, frame_id, timestamp, adaptive)
        preflop = self.preflop.fresh(game.current_state, game.evidence, timestamp, sequence)
        clean = self.preflop.clean_state(game.current_state, game.evidence, timestamp)
        decision = self.opponents.model.strategy_input(game.current_state) if synced else None
        table = {"hero_seat": self.preflop.config.hero_seat, "result": preflop} if preflop else None
        request = StrategyRequest(clean, self.poker.config, self.strategy.config, decision, table, frame_id, timestamp, sequence)
        frozen = game.decisions.detect(request, mode=self.mode, events=tuple(game.event_engine.events),
            evidence=game.evidence, opponents=self.opponents.model.snapshot() if synced else None,
            preflop_config=self.preflop.config.model_dump(mode="json") if self.preflop.config else None,
            running=self.state == "running" and synced)
        if frozen is not None:
            event = game.event_engine.emit("HERO_DECISION_REQUIRED", game.current_state, frame_id, timestamp,
                player_id=game.current_state.current_player, decision_id=frozen.id,
                action_evidence=("visual_turn", "confirmed_cards", "confirmed_amounts"))
            self.decisions.enqueue(frozen, event)
            # A descriptive event changes no poker facts, but consumers must see a contiguous stream.
            if synced:
                self.opponents.model.consume(event)
            if self.preflop.config is not None:
                self.preflop.advance([event], event.sequence, game.current_state, frame_id, timestamp)
        active = self.decisions.active(game.decisions.active)
        if active and (self.decisions.pending or self.decisions.storage_error):
            self.strategy.reset()
            return
        self.strategy.submit(clean, self.poker.config, decision, table, frame_id, timestamp, sequence,
                             self.state == "running", active)

    async def _save_hands(self):
        records = self.observation_state.hands.pending_records
        if not records and not self.pending_events:
            return
        if self.hand_store:
            try:
                await asyncio.to_thread(self.hand_store.save, list(records), list(self.pending_events),
                    {"capture_id": self.capture_id, "source": self.source.kind if self.source else None,
                     "name": self.source.name if self.source else None, "mode": self.mode})
            except Exception:
                self.storage_error = "No se pudieron guardar las manos. La captura se ha detenido para evitar perder el historial."
                raise
        records.clear()
        self.pending_events.clear()
        self.storage_error = None

        self.evaluations.kick()

    async def start(self, source: VideoSource, owned_path: Path | None = None) -> dict:
        async with self._control:
            await self.decisions.flush()
            if self.storage_error:
                await self._save_hands()
            if self._task and not self._task.done():
                raise CaptureConflict("Detén la captura actual antes de abrir otra fuente.")
            async with self.preflop.lock:
                await self.preflop.flush()
            async with self.opponents.lock:
                await self.opponents.flush()
            await self.strategy.flush()
            processor = await asyncio.to_thread(self.processor_factory)
            try:
                await asyncio.to_thread(source.start)
                next_game, next_capture = GameStateEngine(), str(uuid4())
                if self.hand_store and self.mode:
                    await asyncio.to_thread(self.hand_store.start_review_session, next_game.current_state.scope_id,
                                            next_capture, self.mode, self.feedback_release)
            except Exception:
                await asyncio.to_thread(source.stop)
                raise
            self.source = source
            self.capture_id = next_capture
            self.state = "running"
            self.error = None
            self.preview = None
            self.observation_state = next_game
            self.session_release = self.feedback_release
            async with self.opponents.lock:
                self.opponents.reset(self.observation_state.current_state.scope_id)
            async with self.preflop.lock:
                self.preflop.reset()
            self.poker.reset()
            self.strategy.reset()
            self.decisions.reset()
            self.pipeline = FramePipeline(source, processor, self._publish, self.queue_size)
            self._task = asyncio.create_task(self._run(source, owned_path))
            self._notify()
            return self.status()

    async def _run(self, source: VideoSource, owned_path: Path | None):
        final_state = "stopped"
        try:
            await self.pipeline.run()
            final_state = "ended" if self.pipeline.eof else "stopped"
        except SourceError as exc:
            final_state, self.error = "error", str(exc)
        except Exception:
            logger.exception("Capture pipeline failed")
            final_state, self.error = "error", "La captura se interrumpió durante la lectura o el procesamiento."
        finally:
            await asyncio.to_thread(source.stop)
            if owned_path is not None:
                owned_path.unlink(missing_ok=True)
            self.observation_state.hands.interrupt(f"capture_{final_state}")
            if self.observation_state.current_state.hand_status == "active":
                previous_state = self.observation_state.current_state
                self.observation_state.current_state = replace(self.observation_state.current_state, hand_status="incomplete")
                observation = self.observation_state.last_observation
                self.observation_state.changes.compare(previous_state, self.observation_state.current_state,
                    observation.frame_id, observation.source_timestamp)
                self.pending_events.append(self.observation_state.event_engine.emit("CAPTURE_ENDED",
                    self.observation_state.current_state, observation.frame_id, observation.source_timestamp))
            try:
                await self.decisions.flush()
                await self._save_hands()
                async with self.opponents.lock:
                    await self._opponents_locked()
                if self.hand_store and self.mode:
                    await asyncio.to_thread(self.hand_store.stop_review_capture, self.observation_state.current_state.scope_id)
                self.feedback_revision += 1
            except Exception:
                logger.exception("Hand persistence failed")
                final_state, self.error = "error", self.decisions.storage_error or self.storage_error or self.opponents.storage_error or self.error or "No se pudo finalizar el archivo de la captura."
            # Announce completion only after workers and owned files are released.
            self.state = final_state
            async with self.preflop.lock:
                self.preflop.invalidate()
            self._analyze()
            self._notify()

    async def stop(self, capture_id: str | None = None) -> dict:
        async with self._control:
            if capture_id is not None and capture_id != self.capture_id:
                raise CaptureConflict("Esta captura ya no es la actual.")
            if self.pipeline:
                self.pipeline.request_stop()
            if self._task:
                await self._task  # Let an in-flight decoder finish before release.
            self.state = "stopped"
            self.preview = None
            self.error = None
            self._notify()
            return self.status()

    async def push_screen(self, capture_id: str, data: bytes) -> None:
        async with self._control:
            if (capture_id != self.capture_id or self.state != "running"
                    or not isinstance(self.source, ScreenCaptureSource)):
                raise CaptureConflict("Esta captura de pantalla ya no está activa.")
            await asyncio.to_thread(self.source.push, data)

    async def close(self) -> None:
        await self.stop()
        await self.poker.close()
        await self.strategy.close()
        await self.strategy.flush()
        await self.evaluations.close()
        await self.decisions.flush()
        if self.decisions.task:
            await self.decisions.task
        await self.preflop.flush()
        await self.opponents.flush()
        self._temp.cleanup()
