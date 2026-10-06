# Arquitectura de BotTrader

## Capas

### Market

Responsable de obtener información pública de Binance. No toma decisiones y no ejecuta órdenes.

### Strategy

Calcula indicadores y score. Es determinista y no conoce la cuenta de Binance ni la base de datos.

### Risk

Autoriza o rechaza nuevas posiciones y calcula tamaño, stop loss y take profit.

### Brokers

`PaperBroker` simula ejecución. `BinanceSpotBroker` firma y envía órdenes Spot.

### Services

Orquestan estrategia, riesgo, broker y persistencia.

### Persistence

PostgreSQL conserva señales, trades, backtests, eventos de riesgo y estado de runtime.

### API

Expone análisis, backtesting, status y ticks administrativos.

### Worker

Ejecuta ciclos continuos. Usa un PostgreSQL advisory lock global para mantener una sola instancia activa.

## Flujo PAPER

```text
klines -> indicadores -> score -> risk -> PaperBroker -> trades
```

## Flujo LIVE

```text
klines -> indicadores -> score -> risk -> MARKET BUY
                                        |
                                        v
                                   OCO protection
                                  /              \
                                 TP              SL
```

Una salida por señal cancela primero la protección OCO y luego ejecuta la venta de mercado.

## Consistencia

La base incluye un índice parcial único para impedir dos trades OPEN del mismo símbolo y modo.

El worker utiliza un advisory lock adicional para evitar procesos duplicados.

## Política ante errores de ejecución

Las operaciones de escritura hacia Binance no se reintentan automáticamente cuando el resultado puede ser ambiguo. Primero debe reconciliarse el estado con el exchange.

## PostgreSQL 9.5

No se usan identity columns ni características introducidas en versiones recientes. Las claves numéricas usan secuencias compatibles con PostgreSQL 9.5.
