# Security Policy

## Secrets

Nunca deben versionarse:

- `.env`
- Binance API Key
- Binance API Secret
- tokens administrativos
- credenciales PostgreSQL de producción

## Binance

La clave de BotTrader debe tener solamente los permisos necesarios para lectura y Spot Trading.

No habilitar retiros.

Cuando Binance lo permita, limitar la API Key a la IP del servidor que ejecuta BotTrader.

## LIVE safety gates

LIVE requiere simultáneamente:

- `TRADING_MODE=LIVE`
- `LIVE_TRADING_ENABLED=true`
- `LIVE_CONFIRMATION=ENABLE_LIVE_SPOT`
- API Key
- API Secret

El valor predeterminado es PAPER.

## Incident response

Si aparece un evento `PROTECTION_FAILED` o una posición con `protection_status=UNKNOWN`, detener el worker y verificar directamente en Binance el estado de órdenes y balances antes de reanudar.

No reintentar manualmente una orden cuyo estado de ejecución sea desconocido hasta reconciliarla con Binance.
