from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.api.router import router
from app.core.config import get_settings
from app.core.exceptions import BotTraderError
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Binance Spot trading research, paper trading, backtesting "
        "and controlled execution."
    ),
)


@app.exception_handler(BotTraderError)
async def handle_bot_error(_: Request, exc: BotTraderError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    path = Path(__file__).parent / "web" / "dashboard.html"
    return HTMLResponse(path.read_text(encoding="utf-8"))


app.include_router(router)
