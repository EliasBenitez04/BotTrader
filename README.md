# BotTrader

Plataforma profesional de trading algorítmico para Binance Spot.

## Objetivo

Construir un sistema por fases:

1. **Paper Trading**: analizar mercado real y simular operaciones sin ejecutar órdenes.
2. **Backtesting**: validar estrategias con datos históricos y métricas cuantitativas.
3. **Live Spot controlado**: operar capital real pequeño con límites estrictos de riesgo.
4. **Automatización**: ejecución continua con protecciones, auditoría y observabilidad.

## Principios de diseño

- `PAPER` es el modo predeterminado.
- El modo `LIVE` requiere activación explícita.
- Sin Futures ni apalancamiento en V1.
- Sin permisos de retiro.
- Gestión de riesgo desacoplada de la estrategia.
- Persistencia compatible con PostgreSQL 9.5.25.
- Código modular, testeable y auditable.

> Este software automatiza reglas de trading; no garantiza rentabilidad.
