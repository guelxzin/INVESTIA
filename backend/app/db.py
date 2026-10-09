from datetime import datetime
from sqlalchemy import create_engine, String, Float, Integer, ForeignKey, DateTime
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from .config import settings

engine = create_engine(settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
Session = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

class PortfolioAsset(Base):
    __tablename__ = "portfolio_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)

class AssetPrice(Base):  # histórico real coletado pelo poller
    __tablename__ = "asset_prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    price: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(50))
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
