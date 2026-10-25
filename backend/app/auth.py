"""Password once, signed expiring HttpOnly session for frames and WebSocket."""
import asyncio
import base64
from collections import OrderedDict
import ctypes
import hashlib
import hmac
import json
import os
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

router = APIRouter(prefix="/api/auth", tags=["authentication"])
COOKIE = "zeros_session"
_crypt_lock = threading.Lock()


class Sessions:
    def __init__(self):
        credential = os.getenv("APP_AUTH_HTPASSWD", "")
        self.user, _, self.hashed = credential.partition(":")
        self.enabled = bool(credential)
        if self.enabled and (not self.user or not self.hashed.startswith(("$2a$", "$2b$", "$2y$"))):
            raise ValueError("APP_AUTH_HTPASSWD debe contener usuario y hash bcrypt.")
        self.key = hashlib.sha256(os.getenv("APP_SESSION_SECRET", credential).encode()).digest()
        self.ttl = 12 * 60 * 60
        self.attempts = OrderedDict()
        self.lock = asyncio.Semaphore(1)

    def valid(self, token):
        if not self.enabled:
            return True
        if not token or len(token) > 2048:
            return False
        try:
            encoded, signature = token.split(".", 1)
            expected = hmac.new(self.key, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return False
            payload = json.loads(base64.urlsafe_b64decode(encoded))
            return payload["user"] == self.user and time.time() < payload["expires"] <= time.time() + self.ttl + 5
        except (ValueError, KeyError, TypeError):
            return False

    def issue(self):
        payload = {"user": self.user, "expires": int(time.time()) + self.ttl}
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        return encoded + "." + hmac.new(self.key, encoded.encode(), hashlib.sha256).hexdigest()

    def verify(self, user, password):
        # libcrypt is provided by the Linux nginx runtime. No password is logged.
        if len(password.encode()) > 72:
            return False
        with _crypt_lock:
            library = ctypes.CDLL("libcrypt.so.1")
            library.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            library.crypt.restype = ctypes.c_char_p
            result = library.crypt(password.encode(), self.hashed.encode())
            return bool(result) and hmac.compare_digest(result.decode(), self.hashed) and hmac.compare_digest(user.encode(), self.user.encode())


def service(request):
    return request.app.state.sessions


@router.get("/check")
async def check(request: Request):
    return Response(status_code=204 if service(request).valid(request.cookies.get(COOKIE)) else 401,
                    headers={"Cache-Control": "no-store"})


@router.get("/status")
async def status(request: Request):
    auth = service(request)
    return JSONResponse({"enabled": auth.enabled, "authenticated": auth.valid(request.cookies.get(COOKIE))}, headers={"Cache-Control": "no-store"})


@router.get("/page", response_class=HTMLResponse)
async def page():
    return HTMLResponse('''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Acceso · Zeros</title>
<style>body{font:17px system-ui;background:#101711;color:#eef5e9;max-width:380px;margin:12vh auto;padding:24px}label{display:block;margin:20px 0}input,button{box-sizing:border-box;width:100%;padding:14px;margin-top:8px;border-radius:8px;font:inherit}button{background:#c5f47b;border:0;cursor:pointer}p{line-height:1.6;color:#b7c7ad}</style>
<h1>Zeros Poker Lab</h1><p>Introduce tus credenciales para acceder a tu mesa y sesiones.</p>
<form method="post" action="/api/auth/login"><label>Usuario<input name="username" autocomplete="username" required maxlength="80"></label><label>Contraseña<input name="password" type="password" autocomplete="current-password" required maxlength="72"></label><button>Entrar</button></form>
<p>La sesión dura 12 horas. La cámara requiere tu permiso al iniciarla.</p></html>''', headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"})


@router.post("/login")
async def login(request: Request):
    auth = service(request)
    if not auth.enabled:
        raise HTTPException(409, "El acceso local no requiere iniciar sesión.")
    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > 2048:
            raise HTTPException(413, "Formulario demasiado grande.")
    from urllib.parse import parse_qs
    form = parse_qs(body.decode(errors="replace"), max_num_fields=4)
    user, password = form.get("username", [""])[0], form.get("password", [""])[0]
    identity = request.client.host if request.client else "unknown"
    now = time.monotonic()
    count, since = auth.attempts.get(identity, (0, now))
    if now - since > 60:
        count, since = 0, now
    if count >= 5:
        raise HTTPException(429, "Espera un minuto antes de volver a intentarlo.", headers={"Retry-After": "60"})
    if auth.lock.locked():
        raise HTTPException(429, "Hay otro acceso en curso. Reintenta en unos segundos.", headers={"Retry-After": "2"})
    auth.attempts[identity] = (count + 1, since)
    auth.attempts.move_to_end(identity)
    while len(auth.attempts) > 512:
        auth.attempts.popitem(last=False)
    async with auth.lock:
        accepted = await asyncio.to_thread(auth.verify, user, password)
    if not accepted:
        return HTMLResponse('<html lang="es"><meta charset="utf-8"><p>Usuario o contraseña incorrectos.</p><a href="/login">Volver al acceso</a></html>', status_code=401, headers={"Cache-Control": "no-store"})
    auth.attempts.pop(identity, None)
    response = RedirectResponse("/live", status_code=303, headers={"Cache-Control": "no-store"})
    secure = os.getenv("APP_AUTH_COOKIE_SECURE", "").lower() == "true" or request.url.scheme == "https"
    response.set_cookie(COOKIE, auth.issue(), max_age=auth.ttl, httponly=True, secure=secure, samesite="lax", path="/")
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE, path="/", samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response
