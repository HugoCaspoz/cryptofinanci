import asyncio
import logging
import cv2
from datetime import datetime, timezone
from hashlib import sha256
from app.pipeline_engine.memory import process_rss_bytes
from app.game_state_engine.corrections import corrected_game
from time import monotonic
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
                 on_update=None, feedback_release=FeedbackRelease.SESSION_FINISHED, buffer_seconds=10):
        if not 1 <= queue_size <= 8:
            raise ValueError("La capacidad de la cola debe estar entre 1 y 8.")
        if not 10 <= buffer_seconds <= 30:
            raise ValueError("FRAME_BUFFER_SECONDS must be between 10 and 30.")
        self.buffer_seconds = buffer_seconds
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
        self.poker = PokerService(mode, self._notify, on_timing=self._analysis_timing)
        self.preflop = PreflopService(mode, hand_store)
        self.opponents = OpponentService(self.observation_state.current_state.scope_id, mode, hand_store)
        self.strategy = StrategyService(mode, self._notify, hand_store, on_timing=self._analysis_timing)
        self.decisions = DecisionService(mode, hand_store, self._decision_saved)
        self.evaluations = EvaluationService(mode, hand_store, self._notify)
        self.feedback_release = FeedbackRelease(feedback_release)
        self.feedback_revision = 0
        self.session_release = None
        self.analysis_paused = False
        self.edit_revision = 0
        self.last_correction_id = None
        self.pending_important = []
        self.important_count = 0
        self.important_storage_error = None
        self._memory_sample = (0.0, None)

    def _analysis_timing(self, scope_id, frame_id, kind, milliseconds):
        # Background work from an earlier capture must not contaminate a new run.
        if self.pipeline and scope_id == self.observation_state.current_state.scope_id:
            self.pipeline.metrics.record_analysis(kind, frame_id, milliseconds, monotonic())

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

    def session_health(self):
        now = monotonic()
        if now - self._memory_sample[0] >= 5:
            self._memory_sample = (now, process_rss_bytes())
        game = self.observation_state
        return {"process_rss_bytes": self._memory_sample[1],
                "source_seconds": game.last_observation.source_timestamp if game.last_observation else 0,
                "retained": {"event_log": len(game.event_engine.events),
                    "event_keys": len(game.event_engine._frame_keys), "state_changes": len(game.changes.events),
                    "recent_hands": len(game.hands.recent), "decision_keys": len(game.decisions.seen),
                    "decision_actions": len(game.decisions.actions), "opponent_profiles": len(self.opponents.model.profiles),
                    "pending_showdowns": len(self.opponents.model.pending_showdowns),
                    "pending_decisions": len(self.decisions.pending), "pending_images": len(self.pending_important)},
                "limits": {"event_log": 40, "event_keys": 40, "state_changes": 40, "recent_hands": 20,
                    "decision_keys": 512, "decision_actions": 512, "opponent_profiles": 128,
                    "pending_showdowns": 20, "pending_decisions": 1, "pending_images": 3},
                "important_frames_saved": self.important_count, "archive_error": self.important_storage_error}

    async def _flush_important(self):
        while self.pending_important:
            record, jpeg = self.pending_important[0]
            try:
                await asyncio.to_thread(self.hand_store.save_important_frame, record, jpeg)
            except Exception:
                self.important_storage_error = "No se pudo guardar una imagen importante; se conserva pendiente y se detiene la captura."
                raise
            self.important_storage_error = None
            self.pending_important.pop(0)
            self.important_count += 1

    async def _archive_frame(self, metadata, kind, jpeg, error_type=None, hand_id=None, event_sequence=None):
        if self.hand_store is None or not hasattr(self.hand_store, "save_important_frame") or jpeg is None:
            return
        if len(self.pending_important) >= 3:
            raise SourceError("La cola de imágenes pendientes está llena; guarda antes de continuar.")
        identity = sha256(f"{self.capture_id}:{metadata['frame_id']}:{kind}".encode()).hexdigest()
        record = {"id": identity, "capture_id": self.capture_id,
            "scope_id": self.observation_state.current_state.scope_id, "mode": self.mode,
            "frame_id": metadata["frame_id"], "timestamp": metadata["timestamp"],
            "kind": kind, "error_type": error_type, "hand_id": hand_id, "event_sequence": event_sequence,
            "created_at": datetime.now(timezone.utc).isoformat()}
        self.pending_important.append((record, jpeg))
        await self._flush_important()

    async def _frame_error(self, frame, stage, error_type):
        buffered = self.pipeline.buffer.get(frame_id=frame.frame_id)
        if buffered:
            metadata, jpeg = buffered.metadata(), buffered.jpeg
        else:
            ok, encoded = await asyncio.to_thread(cv2.imencode, ".jpg", frame.image,
                [cv2.IMWRITE_JPEG_QUALITY, 85])
            metadata = {"frame_id": frame.frame_id, "timestamp": frame.timestamp}
            jpeg = encoded.tobytes() if ok else None
        await self._archive_frame(metadata, "processing_error", jpeg, f"{stage}:{error_type}")

    def status(self) -> dict:
        observation = self.observation_state.last_observation
        return {
            "session_health": self.session_health(),
            "analysis_control": {"paused": self.analysis_paused, "revision": self.edit_revision,
                                 "last_correction_id": self.last_correction_id},
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
            "strategy": self.strategy.snapshot(self.state == "running" and not self.analysis_paused),
            "decisions": self.decisions.snapshot(self.observation_state.decisions),
            "evaluations": self.evaluations.snapshot(),
            "feedback": self.feedback_status(),
            "preflop": self.preflop.snapshot(self.observation_state.current_state, self.observation_state.evidence,
                observation.source_timestamp if observation else None,
                self.observation_state.event_engine.replay.sequence, self.state == "running" and not self.analysis_paused),
            "hand_storage": {"kind": self.hand_store.kind if self.hand_store else "disabled",
                             "error": self.storage_error},
        }

    def _notify(self):
        self.revision += 1
        if self.on_update:
            self.on_update(self.status())

    async def _publish(self, result: ProcessedFrame) -> dict:
        await self.decisions.flush()  # Never advance the frame while a frozen decision is unsaved.
        sequence = self.observation_state.event_engine.replay.sequence
        was_blocked = self.review_blocked()
        state_started = monotonic()
        self.observation_state.accept(result.observation)
        state_ms = (monotonic() - state_started) * 1000
        self.preview = result.metadata, result.jpeg
        # Revoke an open review before awaiting disk/OCR consumers for the new hand.
        if not was_blocked and self.review_blocked():
            self._notify()
        self.pending_events.extend(e for e in self.observation_state.event_engine.events if e.sequence > sequence)
        hands = self.observation_state.hands
        if hands.active and self.pending_events:
            hands.pending_records.append({**hands.active, "state": asdict(hands.last_state)})
        boundaries = [e for e in self.pending_events if e.type in {"HAND_STARTED", "HAND_FINISHED"}]
        await self._save_hands()
        for event in boundaries:
            await self._archive_frame(result.metadata, event.type.lower(), result.jpeg,
                                      hand_id=event.hand_id, event_sequence=event.sequence)
        async with self.opponents.lock:
            await self._opponents_locked()
        async with self.preflop.lock:
            await self._preflop_locked()
        self._analyze()
        return {"state": state_ms}

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
        if self.analysis_paused:
            self.poker.generation += 1
            self.poker.pending = self.poker.result = self.poker.key = None
            self.poker.status = "paused"
            self.strategy.reset()
            self.observation_state.decisions.active = None
            return
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
            # Only attach the image of this exact observation, including callbacks outside _publish.
            jpeg = (self.preview[1] if self.preview and self.preview[0]["frame_id"] == frame_id
                    and self.preview[0]["timestamp"] == timestamp else None)
            self.decisions.enqueue(frozen, event, jpeg)
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
                       "name": self.source.name if self.source else None, "mode": self.mode,
                       "hero_seat": self.poker.config.hero_seat if self.poker.config else None})
            except Exception:
                self.storage_error = "No se pudieron guardar las manos. La captura se ha detenido para evitar perder el historial."
                raise
        records.clear()
        self.pending_events.clear()
        self.storage_error = None

        self.evaluations.kick()

    async def pause_analysis(self, capture_id):
        async with self._control:
            if capture_id != self.capture_id or self.state != "running" or not self.pipeline:
                raise CaptureConflict("La captura no está en ejecución.")
            if not self.analysis_paused:
                self.analysis_paused = True
                self._analyze()
                await self.pipeline.pause()
                await self.decisions.flush()
                self.edit_revision += 1
                self._notify()
            return self.status()

    async def resume_analysis(self, capture_id):
        async with self._control:
            if capture_id != self.capture_id or self.state != "running" or not self.pipeline:
                raise CaptureConflict("La captura no está en ejecución.")
            if self.analysis_paused:
                game = self.observation_state
                observation = game.last_observation
                if observation:
                    event = game.event_engine.emit("ANALYSIS_RESUMED", game.current_state,
                        observation.frame_id, observation.source_timestamp,
                        action_evidence=(f"resume:{self.edit_revision}",))
                    self.pending_events.append(event)
                    await self._save_hands()
                self.analysis_paused = False
                self.edit_revision += 1
                self.pipeline.resume()
                self._notify()
            return self.status()

    async def correct(self, capture_id, body):
        async with self._control:
            if capture_id != self.capture_id or not self.analysis_paused or self.state != "running":
                raise CaptureConflict("Pausa la captura actual antes de corregir.")
            if self.hand_store is None:
                raise CaptureConflict("No hay almacenamiento para guardar el dataset.")
            existing = await asyncio.to_thread(self.hand_store.correction, str(body.id))
            request = body.model_dump(mode="json", exclude_unset=True)
            if existing:
                if existing["capture_id"] != capture_id or existing["request"] != request:
                    raise CaptureConflict("Ese identificador ya se utilizó para otra corrección.")
                return self.status()
            game = self.observation_state
            observation = game.last_observation
            if (not observation or body.expected_frame_id != observation.frame_id
                    or body.expected_revision != self.edit_revision):
                raise CaptureConflict("El frame o la revisión cambiaron. Recarga la corrección.")
            trial, event = corrected_game(game, body)
            buffered = self.pipeline.buffer.get(frame_id=observation.frame_id)
            jpeg = buffered.jpeg if buffered else self.preview[1] if self.preview else None
            ratio = min(1, 1280 / observation.width, 720 / observation.height)
            record = {"schema_version": 1, "id": str(body.id), "capture_id": capture_id,
                "scope_id": game.current_state.scope_id, "hand_id": game.current_state.hand_id,
                "revision": self.edit_revision + 1, "mode": self.mode,
                "created_at": datetime.now(timezone.utc).isoformat(), "request": request,
                "frame_id": observation.frame_id, "timestamp": observation.source_timestamp,
                "before": asdict(game.current_state), "after": asdict(trial.current_state),
                "observation": asdict(observation), "has_image": jpeg is not None,
                "image_width": buffered.width if buffered else max(1, int(observation.width * ratio)),
                "image_height": buffered.height if buffered else max(1, int(observation.height * ratio)),
                "event_sequence": event.sequence}
            hand_record = ({**trial.hands.active, "state": asdict(trial.current_state),
                "context": {"capture_id": capture_id, "source": self.source.kind,
                            "name": self.source.name, "mode": self.mode}} if trial.hands.active else None)
            # Commit labels, source image, event and hand state before changing memory.
            await asyncio.to_thread(self.hand_store.save_correction, record, event, hand_record, jpeg)
            self.observation_state = trial
            self.last_correction_id = str(body.id)
            self.edit_revision += 1
            self.preflop.invalidate()
            self._analyze()
            self.evaluations.kick()
            self._notify()
            return self.status()

    async def start(self, source: VideoSource, owned_path: Path | None = None) -> dict:
        async with self._control:
            await self._flush_important()
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
            self.analysis_paused = False
            self.edit_revision = 0
            self.last_correction_id = None
            self.important_count = 0
            self.pipeline = FramePipeline(source, processor, self._publish, self.queue_size, on_processed=self._notify, buffer_seconds=self.buffer_seconds, on_error=self._frame_error)
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
            if self.analysis_paused:
                self.analysis_paused = False
                self.edit_revision += 1
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

    async def push_screen(self, capture_id: str, data: bytes, kind: str = "screen") -> None:
        async with self._control:
            if (capture_id != self.capture_id or self.state != "running"
                    or not isinstance(self.source, ScreenCaptureSource) or self.source.kind != kind):
                raise CaptureConflict("Esta fuente de captura ya no está activa.")
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
        await self._flush_important()
        self._temp.cleanup()
        if self.pipeline:
            self.pipeline.buffer.clear()
