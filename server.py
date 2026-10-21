"""
Telegram webhook serveri (aiohttp) + health check endpoint.

Render.com web service **majburiy** ravishda bir portga ulanishi kerak
("No open ports detected" xatosi aks holda deploy'ni 15 daqiqa ushlab turadi
va keyin timeout beradi). Shu sababli bot serverda quyidagilarni qiladi:

  * `POST /webhook` — Telegram yangilanishlarini qabul qiladi
    (`X-Telegram-Bot-Api-Secret-Token` sarlavhasi bilan tekshiriladi);
  * `GET  /health`  — Render health check uchun `200 OK` qaytaradi;
  * `GET  /`        — qisqa ma'lumot.

Server bitta portda (`PORT`, Render'da odatda 10000) ishlaydi.
"""
from __future__ import annotations

import hmac
import logging
import time

from aiohttp import web
from telegram import Update

logger = logging.getLogger(__name__)

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class WebhookServer:
    """aiohttp asosidagi webhook + health serveri."""

    def __init__(
        self,
        application,
        secret_token: str = "",
        webhook_path: str = "/webhook",
        host: str = "0.0.0.0",
        port: int = 10000,
    ) -> None:
        self.application = application
        self.secret_token = secret_token or ""
        self.webhook_path = webhook_path if webhook_path.startswith("/") else f"/{webhook_path}"
        self.host = host
        self.port = port
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._started_at = time.time()
        self._db_ok: bool | None = None
        self._db_checked_at = 0.0

    # ------------------------------------------------------------------
    # Sozlamalar
    # ------------------------------------------------------------------
    def _build_app(self) -> web.Application:
        routes = web.RouteTableDef()

        @routes.get("/health")
        async def health(_request: web.Request) -> web.Response:
            return web.json_response(
                {
                    "status": "ok",
                    "uptime_seconds": round(time.time() - self._started_at, 1),
                    "database": await self._database_status(),
                },
                status=200,
            )

        @routes.get("/")
        async def index(_request: web.Request) -> web.Response:
            return web.json_response(
                {
                    "service": "mahsulot-bot",
                    "status": "ok",
                    "webhook": self.webhook_path,
                },
                status=200,
            )

        @routes.post(self.webhook_path)
        async def webhook(request: web.Request) -> web.Response:
            if not self._check_secret(request):
                logger.warning("Webhook so'rovi noto'g'ri secret token bilan keldi.")
                return web.json_response({"error": "forbidden"}, status=403)

            try:
                payload = await request.json()
            except Exception:  # noqa: BLE001
                return web.json_response({"error": "invalid json"}, status=400)

            if not isinstance(payload, dict):
                return web.json_response({"error": "invalid update"}, status=400)

            try:
                update = Update.de_json(payload, self.application.bot)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Webhook update'ni parse qilib bo'lmadi: %r", exc)
                return web.json_response({"error": "invalid update"}, status=400)

            await self.application.update_queue.put(update)
            return web.json_response({"ok": True}, status=200)

        app = web.Application()
        app.add_routes(routes)
        return app

    def _check_secret(self, request: web.Request) -> bool:
        if not self.secret_token:
            return True
        provided = request.headers.get(SECRET_HEADER, "")
        return hmac.compare_digest(provided, self.secret_token)

    async def _database_status(self) -> str:
        """DB holati (30 soniyada bir tekshiriladi — health check tez bo'lsin)."""
        now_ts = time.time()
        if self._db_ok is not None and now_ts - self._db_checked_at < 30:
            return "ok" if self._db_ok else "down"

        from services import db  # lazy import (siklik import muammosi bo'lmasligi uchun)

        self._db_ok = await db.check_connection()
        self._db_checked_at = now_ts
        return "ok" if self._db_ok else "down"

    # ------------------------------------------------------------------
    # Boshqaruv
    # ------------------------------------------------------------------
    async def start(self) -> None:
        app = self._build_app()
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info(
            "HTTP server ishga tushdi: http://%s:%s (webhook: %s)",
            self.host,
            self.port,
            self.webhook_path,
        )

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            logger.info("HTTP server to'xtatildi.")
