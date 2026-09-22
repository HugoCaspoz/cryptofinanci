import logging

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import ValidationError

from .layout import TableLayout
from .store import LayoutConflict

router = APIRouter(prefix="/api/table-layout", tags=["table layout"])
logger = logging.getLogger(__name__)


def unavailable(exc: Exception):
    logger.warning("Table layout unavailable: %s", exc)
    return HTTPException(503, "No se puede leer o guardar el layout. Comprueba el fichero y sus permisos.")


@router.get("", response_model=TableLayout)
def read_layout(request: Request, response: Response):
    try:
        layout, revision = request.app.state.layouts.read()
    except (OSError, ValidationError) as exc:
        raise unavailable(exc) from exc
    response.headers.update({"ETag": revision, "Cache-Control": "no-store"})
    return layout


@router.put("", response_model=TableLayout)
def save_layout(layout: TableLayout, request: Request, response: Response,
                if_match: str | None = Header(default=None)):
    if if_match is None:
        raise HTTPException(428, "Recarga el layout antes de guardar.")
    try:
        saved, revision = request.app.state.layouts.save(layout, if_match)
    except LayoutConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (OSError, ValidationError) as exc:
        raise unavailable(exc) from exc
    response.headers.update({"ETag": revision, "Cache-Control": "no-store"})
    return saved
