from contextlib import asynccontextmanager
import asyncio
import os

from fastapi import FastAPI

from app.api.routes import router as api_router
from app.config import Settings
from app.version import VERSION
from app.auth import Sessions, router as auth_router
from app.web_security import trusted_origin
from app.card_detector.profiles import CardProfiles, router as profile_router
from app.session_archive import router as session_archive_router
from fastapi.responses import JSONResponse
from app.capture_engine.engine import CaptureEngine
from app.capture_engine.routes import router as capture_router
from app.websocket_engine.routes import router as websocket_router
from app.table_detector.store import LayoutStore
from app.table_detector.routes import router as layout_router
from app.pipeline_engine.processor import FrameProcessor
from app.vision_engine import VisionEngine
from app.event_engine.routes import router as event_router
from app.hand_reconstructor.store import HandStore
from app.hand_reconstructor.routes import router as hand_router
from app.websocket_engine.capture_hub import CaptureHub
from app.poker_engine.routes import router as poker_router
from app.strategy_engine.routes import router as preflop_router
from app.opponent_model.routes import router as opponent_router
from app.strategy_engine.strategy_routes import router as strategy_router
from app.decision_engine.routes import router as decision_router
from app.feedback.routes import router as feedback_router
from app.llm_explainer.routes import router as explanation_router
from app.llm_explainer.service import ExplanationService


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        settings = application.state.settings
        application.state.hand_store = HandStore(settings.database_url,
            os.getenv("HAND_DB_PATH", settings.hand_db_path))
        await asyncio.to_thread(application.state.hand_store.initialize)
        application.state.explainer = ExplanationService(settings, application.state.hand_store)
        application.state.capture_hub = CaptureHub()
        application.state.capture = CaptureEngine(
            on_update=application.state.capture_hub.publish,
            hand_store=application.state.hand_store, mode=settings.mode,
            feedback_release=settings.feedback_release,
            queue_size=application.state.settings.frame_queue_size,
            buffer_seconds=application.state.settings.frame_buffer_seconds,
            processor_factory=lambda: FrameProcessor(VisionEngine(
                application.state.layouts, application.state.settings.card_template_dir,
                application.state.settings.tesseract_cmd, application.state.settings.ocr_decimal_separator)),
        )
        application.state.capture_hub.publish(application.state.capture.status())
        application.state.capture.evaluations.kick()
        try:
            yield
        finally:
            await application.state.capture.close()

    application = FastAPI(title="Zeros API", version=VERSION, lifespan=lifespan)
    application.state.settings = settings or Settings.from_env()
    application.state.layouts = LayoutStore()
    application.state.card_profiles = CardProfiles(os.getenv("CARD_PROFILE_ROOT", str(application.state.layouts.path.parent / "card_profiles")))
    application.state.sessions = Sessions()
    application.include_router(auth_router)
    application.include_router(profile_router)
    application.include_router(session_archive_router)
    application.include_router(api_router)
    application.include_router(capture_router)
    application.include_router(layout_router)
    application.include_router(event_router)
    application.include_router(hand_router)
    application.include_router(poker_router)
    application.include_router(preflop_router)
    application.include_router(opponent_router)
    application.include_router(strategy_router)
    application.include_router(decision_router)
    application.include_router(feedback_router)
    application.include_router(explanation_router)
    application.include_router(websocket_router)

    @application.middleware("http")
    async def private_analysis_cache(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not trusted_origin(request.headers):
            return JSONResponse({"detail": "Origen de navegador no permitido."}, status_code=403)
        if (request.url.path.startswith("/api/") and not request.url.path.startswith("/api/auth/")
                and not application.state.sessions.valid(request.cookies.get("zeros_session"))):
            return JSONResponse({"detail": "Inicia sesión para continuar."}, status_code=401, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        if request.url.path.startswith(("/api/decisions", "/api/feedback", "/api/strategy/archive", "/api/sessions")):
            response.headers["Cache-Control"] = "no-store, private"
        return response
    return application


app = create_app()
