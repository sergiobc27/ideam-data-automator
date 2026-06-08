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

## Decisión sugerida

Hacer el upgrade PAYG cuando haya tarjeta disponible (elimina el riesgo de raíz
y no cambia el costo). Mientras tanto, el healthcheck de 15 min avisará por
email (healthchecks.io) si la API deja de responder — incluida la señal de un
apagón por reclaim, para reaccionar a tiempo (la instancia detenida se puede
reiniciar desde la consola sin perder el disco).
