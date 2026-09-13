"""FastAPI app factory. No FYERS calls and no engine run happens in this process: it only reads
the DB the always-on worker writes and the read-only candle cache, plus a handful of narrow
writes (kill switch, resend, settings, backtest queue/cancel) that were already the dashboard's
only write paths.
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from tradalgo.api.routes import backtests, candles, controls, dashboard, sweeps

DEV_ORIGINS = ["http://127.0.0.1:5173", "http://localhost:5173"]


def create_app(config_path: str | None = None) -> FastAPI:
    app = FastAPI(title="TradAlgo API")
    app.state.config_path = config_path or os.environ.get("TRADALGO_CONFIG", "config.yaml")
    app.add_middleware(
        CORSMiddleware, allow_origins=DEV_ORIGINS, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    for router in (dashboard.router, backtests.router, candles.router, controls.router, sweeps.router):
        app.include_router(router)

    web_dist = Path("web/dist")
    if web_dist.exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.exception_handler(404)
        async def spa_fallback(request: Request, exc):
            if request.url.path.startswith("/api"):
                return JSONResponse(status_code=404, content={"detail": "not found"})
            index = web_dist / "index.html"
            if index.exists():
                return FileResponse(index)
            return JSONResponse(status_code=404, content={"detail": "not found"})

    return app


app = create_app()
