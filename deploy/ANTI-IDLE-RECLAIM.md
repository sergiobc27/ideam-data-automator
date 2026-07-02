# Oracle Always Free y la recuperación de instancias ociosas

## El riesgo

Oracle puede **detener y reclamar** instancias Always Free que considere
ociosas. Criterio publicado (las condiciones se evalúan sobre 7 días seguidos,
percentil 95): CPU bajo el 20%, red bajo el 20% y memoria bajo el 20%
(la de memoria aplica solo a shapes A1 como el nuestro).

Tras terminar el backfill, este servidor quedó casi ocioso: el delta corre dos
veces al día y la API recibe tráfico esporádico. Con el tiempo, el percentil 95
de CPU puede caer bajo el umbral → riesgo real de que el espejo se apague solo.

## Mitigaciones (de menor a mayor solidez)

1. **Carga legítima existente**: el delta (04:00/16:00), el backup (05:00), el
   watchdog y el healthcheck (cada 15 min) generan actividad — puede no bastar
   para el percentil 95 de CPU.
2. **No depender de la suerte**: la opción definitiva es la (3).
3. **RECOMENDADA — Upgrade de la cuenta a "Pay As You Go" (PAYG)**:
   - Las instancias Always Free de cuentas PAYG **no se reclaman por ociosidad**.
   - Mientras SOLO se usen recursos Always Free (este box A1 de 4 OCPU/24GB,
     200GB de bloque, 20GB Object Storage), la factura sigue siendo **$0.00**.
   - Requiere tarjeta de crédito como respaldo. Para garantizar $0 por diseño:
     crear un **Budget** con alerta a $1 (Consola → Billing → Budgets) y NO
     aprovisionar nada fuera de la sección "Always Free eligible".
   - Pasos: Consola de Oracle Cloud → perfil (arriba derecha) →
     **Account Center / Upgrade and Manage Payment** → *Upgrade to Pay As You Go*.
   - Verificación post-upgrade: la instancia muestra que ya no está sujeta a
     "idle instance reclamation" y el costo estimado del mes permanece en $0.

## Decisión pendiente (estado honesto a 2026-07-01)

El upgrade PAYG **no se ha ejecutado**. Es una acción exclusiva del dueño del
proyecto: requiere entrar a la consola de Oracle con la cuenta propietaria y
registrar una tarjeta de crédito. No se puede automatizar ni ejecutar desde
este repositorio. Hasta entonces, el riesgo de reclaim por ociosidad sigue
abierto y se acepta de forma explícita, con estas condiciones:

- **Mitigación actual**: el healthcheck de 15 min avisa por email
  (healthchecks.io) si la API deja de responder, incluida la señal de un
  apagón por reclaim. El disco de bloque sobrevive a un stop de la instancia,
  así que no hay pérdida de datos en ese escenario.
- **RTO estimado con lo que hay hoy**:
  - *Reclaim tipo stop* (el caso documentado por Oracle): detección por el
    email de healthchecks.io más reinicio manual desde la consola. El reinicio
    en sí toma minutos; el tiempo total lo domina cuánto tarde el dueño en ver
    el correo. RTO realista: horas, mismo día. Sin pérdida de datos.
  - *Pérdida total del box* (peor caso, no es el comportamiento del reclaim
    pero se estima por honestidad): reconstrucción con el procedimiento E de
    `docs/RUNBOOK.md`. El backup diario (esquema + `ingest_state` +
    `estaciones`, con copia offsite en Object Storage) permite levantar la
    estructura y reanudar el delta en horas, pero las observaciones históricas
    se re-derivan desde Socrata: el backfill completo toma del orden de días.
    RTO realista: 1 a 4 días para el histórico completo.
- **Acción recomendada al dueño del proyecto**: hacer el upgrade PAYG con
  Budget de alerta a $1 (sección anterior). Elimina el reclaim de raíz y el
  costo sigue en $0 mientras solo se usen recursos Always Free. Es la
  mitigación de mayor retorno y la única que cierra este riesgo.
