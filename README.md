# InvestIA (etapa 1)
Monitor de mercado com dados reais: CoinGecko (cripto), AwesomeAPI (moedas), brapi.dev (ações/FIIs B3, atraso ~15 min).
## Rodar local
    cp .env.example .env
    cd backend && pip install -r requirements.txt
    PYTHONPATH=. uvicorn app.main:app --reload     # http://localhost:8000
Ou: `docker compose up`. Saúde: `/health`, `/ready`. Cadastro/login: `/api/auth/*`. Portfólio: `/api/portfolio`.
## Chaves
brapi.dev: crie um token grátis em brapi.dev e coloque em `BRAPI_TOKEN` (alguns tickers funcionam sem token).
## Publicar
Suba no GitHub → Render → New → Blueprint (usa `render.yaml`; WebSocket e HTTPS já incluídos; domínio em Settings → Custom Domains).
Escolhi Render: Blueprint cria app + PostgreSQL de uma vez e suporta WebSocket.
