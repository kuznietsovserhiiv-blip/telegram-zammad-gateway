import html
import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import qrcode
import qrcode.image.svg
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import __version__
from app.config import Settings, get_settings
from app.database import get_db, init_db
from app.link_service import issue_link_token
from app.telegram import router as telegram_router
from app.zammad import current_zammad_user
from app.zammad_webhook import router as zammad_webhook_router


logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger("telegram_gateway")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("database initialized")
    yield


app = FastAPI(title="Telegram Zammad Gateway", version=__version__, lifespan=lifespan)
app.include_router(telegram_router)
app.include_router(zammad_webhook_router)


class LinkTokenResponse(BaseModel):
    deep_link: str
    qr_svg: str
    expires_at: str
    expires_in: int
    zammad_user: str


def require_same_origin(origin: str | None, settings: Settings) -> None:
    if not origin or origin.rstrip("/") not in settings.origin_allowlist:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin is not allowed")


def render_qr_svg(value: str) -> str:
    image = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=3)
    output = io.BytesIO()
    image.save(output)
    return output.getvalue().decode("utf-8")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/link", response_class=HTMLResponse)
@app.post("/link", response_class=HTMLResponse)
def link_page(settings: Settings = Depends(get_settings)) -> str:
    bot_name = html.escape(settings.telegram_bot_username)
    return f"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Підключити Telegram</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f4f6f8;color:#263238;margin:0;padding:32px}}
.card{{max-width:560px;margin:auto;background:#fff;border-radius:12px;padding:28px;box-shadow:0 4px 20px #0002}}
button,a.action{{display:inline-block;background:#168acd;color:#fff;border:0;border-radius:7px;padding:11px 18px;text-decoration:none;font-size:16px;cursor:pointer}}
#result{{display:none;margin-top:22px}} #qr svg{{width:240px;height:240px}} .muted{{color:#68757d}} .error{{color:#b42318}}
</style></head><body><main class="card">
<h1>Підключити Telegram</h1>
<p>Після створення коду відкрийте @{bot_name} за посиланням або відскануйте QR-код. Код діє 10 хвилин і використовується лише один раз.</p>
<button id="create">Створити код підключення</button><p id="message" class="muted"></p>
<section id="result"><div id="qr"></div><p><a id="deepLink" class="action" rel="noopener">Відкрити Telegram</a></p><p id="expires" class="muted"></p></section>
<script>
const button=document.getElementById('create'), message=document.getElementById('message'), result=document.getElementById('result');
button.addEventListener('click', async()=>{{
 button.disabled=true; message.className='muted'; message.textContent='Створюємо одноразовий код…'; result.style.display='none';
 try{{
  const r=await fetch('./api/v1/link-tokens',{{method:'POST',headers:{{'Accept':'application/json','X-Requested-With':'XMLHttpRequest'}},credentials:'same-origin'}});
  const data=await r.json(); if(!r.ok) throw new Error(data.detail||'Помилка створення коду');
  document.getElementById('qr').innerHTML=data.qr_svg;
  document.getElementById('deepLink').href=data.deep_link;
  document.getElementById('expires').textContent=`Код для ${{data.zammad_user}} дійсний до ${{new Date(data.expires_at).toLocaleTimeString()}}`;
  result.style.display='block'; message.textContent='';
 }}catch(e){{message.className='error';message.textContent=e.message;}}finally{{button.disabled=false;}}
}});
</script></main></body></html>"""


@app.post("/api/v1/link-tokens", response_model=LinkTokenResponse)
async def create_link_token(
    request: Request,
    origin: str | None = Header(default=None),
    x_requested_with: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LinkTokenResponse:
    require_same_origin(origin, settings)
    if x_requested_with != "XMLHttpRequest":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Request marker is missing")

    user = await current_zammad_user(request.headers.get("cookie"), settings)
    issued = issue_link_token(
        db,
        zammad_user_id=user.id,
        zammad_login=user.login,
        ttl_seconds=settings.link_token_ttl_seconds,
    )
    deep_link = f"https://t.me/{settings.telegram_bot_username}?start={issued.token}"
    expires_at = datetime.fromtimestamp(issued.expires_at, tz=timezone.utc).isoformat()
    return LinkTokenResponse(
        deep_link=deep_link,
        qr_svg=render_qr_svg(deep_link),
        expires_at=expires_at,
        expires_in=settings.link_token_ttl_seconds,
        zammad_user=user.display_name,
    )
