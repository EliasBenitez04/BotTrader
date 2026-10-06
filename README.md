# BotTrader

BotTrader es una plataforma modular de trading algorítmico para Binance Spot. Está diseñada para investigar una estrategia, simularla, validarla históricamente y recién después habilitar ejecución real controlada.

## Estado de V1

La rama `feat/trading-platform-v1` incorpora:

- Market data desde Binance Spot.
- Indicadores EMA 20/50/200, RSI, MACD, ATR y volumen relativo.
- Scoring de 0 a 100 con señales BUY / WAIT / SELL.
- Paper trading con comisión y slippage configurables.
- Backtesting histórico con Win Rate, Profit Factor, Max Drawdown, retorno, expectancy y Sharpe por operación.
- Gestión de riesgo por operación, pérdida diaria, drawdown, posiciones máximas y pérdidas consecutivas.
- PostgreSQL 9.5.25 con migraciones Alembic.
- Ejecución Binance Spot firmada por HMAC.
- OCO de protección en Binance para posiciones LIVE.
- Dashboard web.
- API FastAPI.
- Worker automático con PostgreSQL advisory lock para evitar dos workers simultáneos.
- CI con lint, compilación, pruebas y migraciones sobre PostgreSQL 9.5.

## Arquitectura

```text
Binance Market Data
        |
        v
Indicator Engine
        |
        v
Strategy Scoring
        |
        v
Risk Manager
        |
        +------------------+
        |                  |
        v                  v
   Paper Broker      Binance Spot Broker
        |                  |
        +--------+---------+
                 |
                 v
            PostgreSQL
                 |
        +--------+---------+
        |                  |
        v                  v
      API             Dashboard / Worker
```

La estrategia no conoce detalles de Binance y el broker no decide cuándo operar. Esta separación permite usar la misma lógica en backtesting, PAPER y LIVE.

## Requisitos

- Python 3.12
- PostgreSQL 9.5.25
- Git
- Windows 10/11 o Linux

PostgreSQL 9.5 es una versión antigua y fuera de soporte upstream. El proyecto evita funciones modernas incompatibles, pero conviene aislar esa instancia y planificar una actualización futura.

## Instalación rápida en Windows

Clonar y entrar al proyecto:

```powershell
git clone https://github.com/EliasBenitez04/BotTrader.git
cd BotTrader
git checkout feat/trading-platform-v1
```

Preparar Python:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

Crear la base de datos con PostgreSQL y luego editar `.env`. El archivo de referencia es `.env.example`.

Aplicar migraciones:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

Iniciar API y dashboard:

```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

Dashboard:

```text
http://127.0.0.1:8000/dashboard
```

Documentación interactiva:

```text
http://127.0.0.1:8000/docs
```

## Fase 1: PAPER

Es el modo predeterminado.

```env
TRADING_MODE=PAPER
PAPER_INITIAL_CAPITAL=1000
RISK_PER_TRADE=0.01
```

Ejecutar el worker:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

El worker consulta los pares configurados en `SYMBOLS_CSV`, analiza el mercado y simula entradas/salidas. No envía órdenes reales.

## Fase 2: Backtesting

Endpoint:

```http
POST /api/v1/backtests
X-Bot-Token: <BOT_ADMIN_TOKEN>
```

Ejemplo:

```json
{
  "symbol": "BTCUSDT",
  "timeframe": "5m",
  "start_time": "2026-01-01T00:00:00Z",
  "end_time": "2026-03-01T00:00:00Z",
  "initial_capital": 1000,
  "max_candles": 20000
}
```

Métricas persistidas:

- total de operaciones
- operaciones ganadoras/perdedoras
- Win Rate
- Profit Factor
- Max Drawdown
- retorno
- expectancy
- Sharpe por operación
- indicador de muestra mínima

`MIN_BACKTEST_TRADES=100` marca cuándo la muestra alcanza el mínimo configurado. No significa que una estrategia sea rentable por sí sola.

## Fase 3: Binance Spot controlado

Primero usar Binance Spot Testnet.

```env
TRADING_MODE=LIVE
LIVE_TRADING_ENABLED=true
LIVE_CONFIRMATION=ENABLE_LIVE_SPOT
BINANCE_USE_TESTNET=true
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
```

El modo LIVE no queda armado si falta cualquiera de esas condiciones.

Después de una compra, BotTrader intenta crear un OCO en Binance:

- Take Profit
- Stop Loss

Si Binance devuelve un fallo inequívoco al crear la protección, BotTrader intenta cerrar la posición. Si el estado de ejecución es ambiguo, registra un evento CRITICAL y evita reintentos ciegos.

## Fase 4: Automatización

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

El worker:

1. obtiene datos;
2. calcula indicadores;
3. obtiene score;
4. gestiona posiciones existentes;
5. consulta el motor de riesgo;
6. abre una posición solamente si está autorizada;
7. persiste señales, operaciones y eventos;
8. repite según `WORKER_INTERVAL_SECONDS`.

PostgreSQL mantiene un advisory lock para impedir que dos workers de BotTrader operen simultáneamente contra la misma base.

## Límites de riesgo predeterminados

```env
RISK_PER_TRADE=0.01
MAX_DAILY_LOSS=0.03
MAX_DRAWDOWN=0.10
MAX_OPEN_POSITIONS=3
MAX_CONSECUTIVE_LOSSES=3
MAX_POSITION_QUOTE_FRACTION=0.25
STOP_LOSS_PCT=0.01
TAKE_PROFIT_R_MULTIPLE=2.0
```

El tamaño de posición se calcula a partir de equity, precio de entrada y distancia al stop; además queda limitado por el porcentaje máximo del capital permitido por posición.

## Seguridad de API

Las acciones administrativas requieren:

```http
X-Bot-Token: <BOT_ADMIN_TOKEN>
```

No se incluye ningún endpoint HTTP para activar LIVE. Esa decisión se realiza solamente mediante variables de entorno.

Para la API Key de Binance:

- habilitar únicamente lectura y Spot Trading;
- no habilitar retiros;
- restringir por IP cuando sea posible;
- usar una clave independiente para BotTrader;
- comenzar siempre en Testnet.

Nunca subir `.env`, API Key ni API Secret al repositorio.

## Docker

Copiar primero:

```bash
cp .env.example .env
```

API + PostgreSQL:

```bash
docker compose up --build
```

Agregar worker:

```bash
docker compose --profile worker up --build
```

## Calidad

Ejecutar:

```powershell
.\.venv\Scripts\ruff.exe check app tests
.\.venv\Scripts\python.exe -m compileall -q app
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\alembic.exe upgrade head
```

## Aviso

BotTrader es software de automatización y análisis. Los resultados de backtesting o paper trading no garantizan resultados futuros. LIVE debe habilitarse únicamente después de validar estrategia, riesgo, credenciales, conectividad y protección de órdenes.
