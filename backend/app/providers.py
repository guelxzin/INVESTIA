"""Camada de abstração: cada provider devolve cotações REAIS ou levanta erro.
Nada é simulado. Todos os dados trazem source, timestamp e status."""
import time
from abc import ABC, abstractmethod
import httpx

def quote(symbol, name, kind, price, pct, source, ts, status, volume=None, chg=None):
    if chg is None and price is not None and pct is not None:
        chg = price - price / (1 + pct / 100)
    return dict(symbol=symbol, name=name, kind=kind, price=price, change_pct=pct,
                change_abs=chg, volume=volume, source=source,
                timestamp=ts or time.time(), status=status)

class MarketDataProvider(ABC):
    name = "base"; kind = "other"; symbols: dict = {}
    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> list[dict]: ...

class CryptoProvider(MarketDataProvider):  # CoinGecko (público, atrasado ~1-2 min)
    name = "CoinGecko"; kind = "crypto"
    symbols = {"bitcoin": ("BTC", "Bitcoin"), "ethereum": ("ETH", "Ethereum"),
               "solana": ("SOL", "Solana"), "ripple": ("XRP", "XRP")}
    async def fetch(self, c):
        r = await c.get("https://api.coingecko.com/api/v3/simple/price", params={
            "ids": ",".join(self.symbols), "vs_currencies": "brl",
            "include_24hr_change": "true", "include_last_updated_at": "true"})
        r.raise_for_status(); d = r.json(); out = []
        for cid, (sym, nm) in self.symbols.items():
            if cid in d:
                x = d[cid]
                out.append(quote(sym, nm, self.kind, x["brl"], x.get("brl_24h_change"),
                                 self.name, x.get("last_updated_at"), "delayed"))
        return out

class CurrencyProvider(MarketDataProvider):  # AwesomeAPI (sem chave)
    name = "AwesomeAPI"; kind = "currency"
    symbols = {"USD-BRL": "Dólar", "EUR-BRL": "Euro", "GBP-BRL": "Libra"}
    async def fetch(self, c):
        r = await c.get("https://economia.awesomeapi.com.br/last/" + ",".join(self.symbols))
        r.raise_for_status(); d = r.json(); out = []
        for pair, nm in self.symbols.items():
            x = d.get(pair.replace("-", ""))
            if x:
                out.append(quote(pair, nm, self.kind, float(x["bid"]), float(x["pctChange"]),
                                 self.name, int(x["timestamp"]), "delayed", chg=float(x["varBid"])))
        return out

class _BrapiProvider(MarketDataProvider):  # B3 via brapi.dev (atraso ~15 min)
    name = "brapi.dev"
    def __init__(self, token=""): self.token = token
    async def fetch(self, c):
        out = []
        for sym, nm in self.symbols.items():  # 1 por ticker: o plano grátis limita lote
            r = await c.get(f"https://brapi.dev/api/quote/{sym}", params={"token": self.token})
            r.raise_for_status()
            for x in r.json().get("results", []):
                out.append(quote(sym, nm, self.kind, x.get("regularMarketPrice"),
                                 x.get("regularMarketChangePercent"), self.name, None,
                                 "delayed", x.get("regularMarketVolume"), x.get("regularMarketChange")))
        return out

class StockProvider(_BrapiProvider):
    kind = "stock"; symbols = {"PETR4": "Petrobras PN", "VALE3": "Vale ON", "ITUB4": "Itaú PN"}

class FIIProvider(_BrapiProvider):
    kind = "fii"; symbols = {"MXRF11": "Maxi Renda", "HGLG11": "CSHG Logística"}
