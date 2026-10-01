# Trader service (pendiente — iteración 2)

Flujo: `Signal Engine → Position Sizing → Risk Engine → BrokerAdapter → Trading 212 Demo`.

- Se ejecuta como worker en Railway (persistente si se necesita WebSocket; cron en otro caso).
- Registra **todas** las decisiones en `signals`, incluidas las rechazadas y NO TRADE.
- Usa `client_order_id` = `Signal.idempotency_key` para evitar órdenes duplicadas.
- Reconciliación periódica de cartera local vs broker; si no cuadra, el Risk Engine bloquea.
- LIVE requiere `TRADING_MODE=LIVE` y `LIVE_TRADING_ENABLED=true`.
