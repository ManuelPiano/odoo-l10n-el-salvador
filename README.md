![Odoo 18.0](https://img.shields.io/badge/Odoo-18.0-714B67?style=flat-square&logo=odoo)
![License: LGPL-3](https://img.shields.io/badge/License-LGPL--3-blue?style=flat-square)
![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python)
![Tests 103](https://img.shields.io/badge/tests-103%20passing-brightgreen?style=flat-square)

# Localización de El Salvador — Facturación Electrónica (DTE)

Módulo de Odoo 18 que emite Documentos Tributarios Electrónicos (DTE) ante el
**Ministerio de Hacienda de El Salvador**: genera el JSON, lo valida contra los
esquemas oficiales, lo firma (JWS RS512), lo transmite y gestiona contingencia
e invalidación.

> Fork de [DIAL-Studio/odoo-l10n-el-salvador](https://github.com/DIAL-Studio/odoo-l10n-el-salvador)
> con auditoría de seguridad, correcciones de cumplimiento y port a Odoo 18.
> Versión actual: `18.0.1.22.0`.

---

## Qué hace

| Área | Detalle |
|------|---------|
| **Documentos** | Factura de Consumidor Final (01, esquema v2), Crédito Fiscal (03, v4), Nota de Crédito (05, v4), Nota de Débito (06, v4). |
| **Validación** | Cada DTE se valida contra el JSON Schema oficial del MH antes de guardarse y antes de firmarse. Un documento inválido no avanza y el usuario ve la lista de errores. |
| **Numeración** | Número de control correlativo sin saltos por empresa, tipo, establecimiento y punto de venta (`DTE-03-M001P001-000000000000001`). |
| **Firma** | JWS RS512 con el certificado XML del MH, sin Java ni firmador externo. |
| **Transmisión** | Envío al MH con caché de token, selección de ambiente (pruebas / producción) por empresa y soporte multiempresa. |
| **Contingencia** | Cron cada 5 minutos que reenvía documentos pendientes; si el MH no responde, el documento vuelve a contingencia sin perder la traza. |
| **Invalidación** | Anulación desde Odoo; si el MH la rechaza, el DTE sigue procesado y con su sello. |
| **Bitácora** | Registro de cada intento (envío, invalidación, contingencia), persistente aunque falle la comunicación. |
| **Catálogos** | CAT-008 distritos y CAT-013 municipios oficiales (división territorial 2024: 262 distritos, 44 municipios), CAT-009, 015, 016, 017, 019 (989 CIIU), 022. |
| **Impresión** | Reporte QWeb del DTE con código QR de verificación. |

## Seguridad

- **Credenciales del MH** en `ir.config_parameter`, nunca en campos ni en el código.
- **Conector privado**: los métodos que leen credenciales o devuelven el token no son invocables por RPC.
- **Certificado** en un campo restringido a administradores; nadie más puede leer la clave privada.
- **Permisos por grupo**: catálogos de solo lectura para usuarios internos; la bitácora solo la modifica el sistema; regla multiempresa sobre la bitácora.
- **Campos del DTE protegidos**: estado, sello y número de control solo cambian por las acciones del flujo, no por escritura directa ni importación.
- **Un DTE con sello de recepción** nunca vuelve a borrador ni se reenvía.

## Requisitos

| Componente | Versión |
|------------|---------|
| Odoo | 18.0 (`base`, `account`, `account_debit_note`) |
| Python | 3.10+ |
| Librerías | `requests`, `cryptography`, `qrcode`, `jsonschema` |

```bash
pip install requests cryptography qrcode jsonschema
```

La imagen oficial `odoo:18.0` no incluye `jsonschema`. En Docker:

```dockerfile
FROM odoo:18.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3-jsonschema \
    && rm -rf /var/lib/apt/lists/*
USER odoo
```

## Instalación

1. Ubicar el módulo dentro del `addons_path` de Odoo (clonar, symlink o agregar la ruta en `odoo.conf`).
2. *Apps → Actualizar lista de aplicaciones* → instalar **Localización de El Salvador - Facturación Electrónica (DTE)**.
3. Configurar la empresa y las credenciales (ver abajo).

Guía detallada: [`docs/instalacion.md`](docs/instalacion.md).

## Configuración mínima para emitir

**Empresa** (*Ajustes → Empresas*):

- NIT y NRC, actividad económica (CAT-019), teléfono y correo.
- Distrito MH (define departamento, municipio y distrito) y dirección.
- Código de establecimiento `M001`/`S001`/`B001`/`P001` y punto de venta `P001`.
- Ambiente `00` (pruebas) o `01` (producción) y certificado `.crt` del MH (solo administradores).

**Credenciales** (*Ajustes → Técnico → Parámetros del sistema*):

| Clave | Valor |
|-------|-------|
| `l10n_sv.api_user_<id_empresa>` | Usuario de la API del MH |
| `l10n_sv.api_password_<id_empresa>` | Contraseña de la API del MH |

Luego usar **Probar conexión con MH** en la empresa.

**Clientes**: para CCF, NC y ND necesitan NIT, NRC, actividad económica, distrito y dirección. Para consumidor final basta NIT o DUI/pasaporte.

**Notas de crédito y débito**: se crean desde el CCF ya procesado (*Nota de crédito* / *Nota de débito*); el módulo exige que el documento de origen tenga sello del MH.

## Flujo del DTE

```
borrador → JSON generado → firmado → enviado → procesado (sello MH)
                                         ↘ rechazado → reenvío (máx. 5)
                     firmado → contingencia → cron de reenvío
procesado → invalidando → invalidado
```

Detalle de estados, cron y asistentes: [`docs/flujo-dte.md`](docs/flujo-dte.md).

## Pruebas

```bash
odoo-bin -d <base> -u l10n_sv_dte --test-enable --test-tags=/l10n_sv_dte --stop-after-init
```

103 pruebas en `tests/`: generación y cuadratura del JSON, validación contra esquemas de FCF/CCF/NC/ND, numeración, firma, cliente HTTP, flujo completo, seguridad y permisos, multiempresa, manejo de fallos de red y catálogo territorial.

## Estructura

```
l10n_sv_dte/
├── __manifest__.py
├── CLAUDE.md                      # Reglas del proyecto para Claude Code
├── models/
│   ├── account_move.py            # Generación JSON, máquina de estados, envío, invalidación
│   ├── l10n_sv_dte_schema.py      # Validación contra JSON Schema del MH
│   ├── l10n_sv_signer.py          # Firma JWS RS512 + lectura del certificado
│   ├── l10n_sv_api.py             # Cliente HTTP del MH (privado)
│   ├── res_company.py / res_partner.py / account_tax.py
│   ├── l10n_sv_municipio.py       # Distritos CAT-008 con municipio CAT-013
│   ├── l10n_sv_dte_log.py         # Bitácora
│   └── l10n_sv_dte_send_wizard.py # Envío masivo
├── data/
│   ├── schemas/                   # JSON Schema oficiales (FCF v2, CCF/NC/ND v4)
│   └── *.csv                      # Catálogos MH
├── migrations/                    # Certificado (1.17.0) y catálogo territorial (1.21.0)
├── security/                      # ACL por grupo + regla multiempresa
├── views/
├── docs/
└── tests/
```

## Pendiente

- Esquemas y validación de Nota de Remisión (04), Sujeto Excluido (14), Exportación (11) e invalidación.
- Hora de anulación en hora de El Salvador (hoy en UTC).
- Revisión del reporte PDF y la interfaz en Odoo 18.

## Documentación

| Documento | Descripción |
|-----------|-------------|
| [Instalación](docs/instalacion.md) | Requisitos, configuración inicial, credenciales |
| [Flujo DTE](docs/flujo-dte.md) | Máquina de estados, cron, asistentes |
| [API MH](docs/api-mh.md) | Endpoints, autenticación, manejo de errores |
| [Firma digital](docs/firma-digital.md) | JWS RS512, certificado, solución de problemas |
| [Catálogos](docs/catalogos.md) | Catálogos MH y geográficos |

## Licencia y créditos

LGPL-3 (ver [`LICENSE`](LICENSE)). Módulo original de
[DIAL Studio](https://www.linkedin.com/company/dial-studio/); este fork
conserva su autoría y licencia.
