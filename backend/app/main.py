import asyncio, hashlib, hmac, logging, os, time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import httpx, jwt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, text
from .config import settings
from .db import Base, engine, Session, User, PortfolioAsset, AssetPrice
from .providers import CryptoProvider, CurrencyProvider, StockProvider, FIIProvider

log = logging.getLogger("investia")
logging.basicConfig(level=logging.INFO)
PROVIDERS = [CryptoProvider(), CurrencyProvider(), StockProvider(settings.brapi_token), FIIProvider(settings.brapi_token)]
CACHE: dict[str, dict] = {}          # último dado REAL de cada símbolo
PSTATUS = {p.name: {"ok": None, "last": None, "error": None} for p in PROVIDERS}
CLIENTS: set[WebSocket] = set()

async def broadcast(msg):
    for ws in list(CLIENTS):
        try: await ws.send_json(msg)
        except Exception: CLIENTS.discard(ws)

async def poll_provider(p, client):
    while True:
        await broadcast({"type": "status", "state": "updating"})
        try:
            quotes = await p.fetch(client)
            for q in quotes:
                if q["price"] is None: continue
                CACHE[q["symbol"]] = q
                with Session() as s:
                    s.add(AssetPrice(symbol=q["symbol"], price=q["price"], source=q["source"])); s.commit()
            PSTATUS[p.name] = {"ok": True, "last": time.time(), "error": None}
        except Exception as e:  # nunca inventar: marca como erro e mantém o último valor real
            log.warning("provider %s falhou: %s", p.name, type(e).__name__)
            PSTATUS[p.name].update(ok=False, error=type(e).__name__)
            for q in CACHE.values():
                if q["source"] == p.name: q["status"] = "error"
        await broadcast({"type": "snapshot", "quotes": list(CACHE.values()), "providers": PSTATUS})
        await asyncio.sleep(settings.poll_seconds)

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    client = httpx.AsyncClient(timeout=10, headers={"User-Agent": "InvestIA/1.0"})
    tasks = [asyncio.create_task(poll_provider(p, client)) for p in PROVIDERS]
    yield
    for t in tasks: t.cancel()
    await client.aclose()

app = FastAPI(title="InvestIA", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                   allow_methods=["*"], allow_headers=["*"])

# ---------- auth ----------
bearer = HTTPBearer()
def hash_pw(pw, salt=None):
    salt = salt or os.urandom(16)
    return salt.hex() + ":" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000).hex()
def check_pw(pw, stored):
    salt, h = stored.split(":")
    return hmac.compare_digest(hash_pw(pw, bytes.fromhex(salt)).split(":")[1], h)
def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> int:
    try: return int(jwt.decode(cred.credentials, settings.secret_key, algorithms=["HS256"])["sub"])
    except Exception: raise HTTPException(401, "Token inválido")

class Cred(BaseModel):
    email: EmailStr; password: str = Field(min_length=8, max_length=128)

@app.post("/api/auth/register", status_code=201)
def register(c: Cred):
    with Session() as s:
        if s.scalar(select(User).where(User.email == c.email)): raise HTTPException(409, "E-mail já cadastrado")
        s.add(User(email=c.email, password_hash=hash_pw(c.password))); s.commit()
    return {"ok": True}

@app.post("/api/auth/login")
def login(c: Cred):
    with Session() as s:
        u = s.scalar(select(User).where(User.email == c.email))
    if not u or not check_pw(c.password, u.password_hash): raise HTTPException(401, "Credenciais inválidas")
    exp = datetime.now(timezone.utc) + timedelta(hours=12)
    return {"token": jwt.encode({"sub": str(u.id), "exp": exp}, settings.secret_key, algorithm="HS256")}

# ---------- mercado ----------
@app.get("/api/quotes")
def quotes(kind: str | None = None):
    return [q for q in CACHE.values() if not kind or q["kind"] == kind]

@app.get("/api/history/{symbol}")
def history(symbol: str, limit: int = 500):
    with Session() as s:
        rows = s.scalars(select(AssetPrice).where(AssetPrice.symbol == symbol.upper())
                         .order_by(AssetPrice.ts.desc()).limit(min(limit, 2000))).all()
    return [{"ts": r.ts.isoformat(), "price": r.price} for r in reversed(rows)]

# ---------- portfólio ----------
class Position(BaseModel):
    symbol: str; quantity: float = Field(gt=0); avg_price: float = Field(ge=0)

@app.post("/api/portfolio", status_code=201)
def add_position(p: Position, uid: int = Depends(current_user)):
    with Session() as s:
        s.add(PortfolioAsset(user_id=uid, symbol=p.symbol.upper(), quantity=p.quantity, avg_price=p.avg_price)); s.commit()
    return {"ok": True}

@app.get("/api/portfolio")
def portfolio(uid: int = Depends(current_user)):
    with Session() as s:
        rows = s.scalars(select(PortfolioAsset).where(PortfolioAsset.user_id == uid)).all()
    items, total, cost = [], 0.0, 0.0
    for r in rows:
        q = CACHE.get(r.symbol); price = q["price"] if q else None
        val = price * r.quantity if price is not None else None
        c = r.avg_price * r.quantity; cost += c
        if val is not None: total += val
        items.append(dict(symbol=r.symbol, quantity=r.quantity, avg_price=r.avg_price, price=price,
                          value=val, pnl=None if val is None else val - c,
                          pnl_pct=None if val is None or not c else (val / c - 1) * 100,
                          status=q["status"] if q else "unavailable", source=q["source"] if q else None))
    return dict(items=items, total_value=total, total_cost=cost, pnl=total - cost)

# ---------- saúde ----------
@app.get("/health")
def health(): return {"status": "ok"}

@app.get("/ready")
def ready():
    try:
        with Session() as s: s.execute(text("SELECT 1")); db = True
    except Exception: db = False
    return {"database": db, "providers": PSTATUS, "ws_clients": len(CLIENTS), "ready": db}

# ---------- websocket ----------
@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept(); CLIENTS.add(ws)
    try:
        await ws.send_json({"type": "snapshot", "quotes": list(CACHE.values()), "providers": PSTATUS})
        while True: await ws.receive_text()   # mantém a conexão aberta
    except WebSocketDisconnect: pass
    finally: CLIENTS.discard(ws)

FRONT = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(FRONT):
    app.mount("/static", StaticFiles(directory=FRONT), name="static")
    @app.get("/")
    def index(): return FileResponse(os.path.join(FRONT, "index.html"))
