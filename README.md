![Odoo 18.0](https://img.shields.io/badge/Odoo-18.0-714B67?style=flat-square&logo=odoo)
![License: LGPL-3](https://img.shields.io/badge/License-LGPL--3-blue?style=flat-square)
![Python 3](https://img.shields.io/badge/Python-3-3776AB?style=flat-square&logo=python)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)

# Localización de El Salvador — Facturación Electrónica (DTE)

Módulo de **facturación electrónica** para Odoo 18 que implementa el
Documento Tributario Electrónico (DTE) conforme a los requerimientos del
**Ministerio de Hacienda de El Salvador**.

> Cumple con la Ley de Firma Electrónica y el Reglamento de
> Comprobantes de Crédito Fiscal, Facturas y Documentos Equivalentes.

<p align="center">
  <a href="https://ko-fi.com/dialstudio">
    <img src="https://cdn.ko-fi.com/cdn/kofi3.png?v=3" alt="Support me on Ko-fi" height="52">
  </a>
</p>

---

## Características

- **Tipos de DTE**: FCF-01, CCF-03, NC-05, ND-06, FSE-14. Extensible
  a NR-04, FEX-11, Retención-07, Donación-15.
- **Firma JWS RS512** con certificado XML del MH — sin Java, sin
  dependencias externas.
- **Catálogos precargados**: CAT-009, 015, 016, 017, 019, 022 +
  municipios + CIIU Rev 4 (989 códigos).
- **Envío automático** al MH con caché de token JWT y selección de
  ambiente (test / producción).
- **Invalidación** de DTE desde la interfaz de Odoo.
- **Contingencia** automática con cron de reenvío cada 5 minutos.
- **QR de verificación** generado en SVG (puro Python, sin Pillow).
- **Reporte QWeb** de impresión del DTE con QR e identificadores.
- **Wizard de envío masivo** para procesar lotes de facturas.
- **Bitácora completa** de cada intento (envío, invalidación, contingencia).
- **Suite de tests** con 50+ tests bajo `TransactionCase`.

## Requisitos

| Componente | Versión |
|------------|---------|
| Odoo | 18.0 |
| Python | 3.10+ |
| Dependencias | `requests`, `cryptography`, `qrcode`, `jsonschema` |

## Instalación

### Ubicación del módulo

Odoo necesita encontrar este directorio dentro de su `--addons-path` (el
parámetro `addons_path` en `odoo.conf`). Opciones:

| Opción | Comando |
|--------|---------|
| **Clonar dentro del addons-path** | `cd /path/to/odoo/addons && git clone https://github.com/dialstudio/l10n_sv_dte` |
| **Symlink desde el addons-path** | `ln -s /ruta/donde/clonaste/l10n_sv_dte /path/to/odoo/addons/l10n_sv_dte` |
| **Agregar al addons-path** | Añadir en `odoo.conf`: `addons_path = /path/to/other/addons,/ruta/del/repositorio` |

### Dependencias Python

```bash
pip install requests cryptography qrcode jsonschema
```

### Instalación en Odoo

```bash
# 1. Clonar / symlink / apuntar addons_path (ver tabla arriba)

# 2. Activar el módulo
#    - Apps → Update Apps List
#    - Buscar "Localización de El Salvador" → Instalar
```

Configuración inicial detallada en
[`docs/instalacion.md`](docs/instalacion.md).

## Documentación

| Documento | Descripción |
|-----------|-------------|
| [Instalación](docs/instalacion.md) | Requisitos, configuración inicial, credenciales |
| [Flujo DTE](docs/flujo-dte.md) | Máquina de estados, cron, wizards, recetas |
| [API MH](docs/api-mh.md) | Endpoints REST, autenticación, manejo de errores |
| [Firma Digital](docs/firma-digital.md) | JWS RS512, certificado, troubleshooting |
| [Catálogos](docs/catalogos.md) | Catálogos MH y geográficos |

## Estado del proyecto

| Fase | Estado | Área |
|------|--------|------|
| 1 | ✅ | Campos, migración de credenciales, UUID/numeroControl |
| 2 | ✅ | Catálogos + CIIU |
| 3 | ✅ | JWS signer, API MH, contingencia, invalidación |
| 4 | ✅ | JSON DTE completo (resumen, documentoRelacionado, pagos) |
| 5 | ✅ | State machine, bitácora, wizard, cron |
| 6 | ✅ | QR + reporte QWeb |
| 7 | ✅ | Tests + documentación |

## Arquitectura

```
l10n_sv_dte/
├── __manifest__.py
├── models/
│   ├── account_move.py           # Generación JSON + state machine
│   ├── account_tax.py            # Mapeo a l10n_sv.tributo
│   ├── res_company.py            # Configuración MH de la compañía
│   ├── res_partner.py            # NIT, NRC, municipio
│   ├── l10n_sv_signer.py         # JWS RS512 + parser de certificado
│   ├── l10n_sv_api.py            # Cliente HTTP del MH
│   ├── l10n_sv_dte_log.py        # Bitácora de intentos
│   └── l10n_sv_dte_send_wizard.py # Wizard de envío masivo
├── data/                         # CSVs de catálogos + cron
├── views/                        # Vistas + reporte QWeb
├── security/
├── docs/                         # Documentación funcional
└── tests/                        # 50+ tests
```

## Seguridad

- **Sin credenciales en el código**. Las credenciales MH se almacenan
  en `ir.config_parameter`, nunca en `res.company`.
- **Sin certificados en el repositorio**. El `.crt` se sube por UI
  como `ir.attachment`.
- **Licencia**: LGPL-3.

## Contribuir

Las contribuciones son bienvenidas. Por favor:

1. Hacer fork del repositorio.
2. Crear una rama con tu cambio (`git checkout -b feat/mi-cambio`).
3. Hacer commit con mensajes descriptivos.
4. Abrir un Pull Request.

Reporta bugs o sugerencias en
[GitHub Issues](https://github.com/dialstudio/l10n_sv_dte/issues).

<p align="center">
  Hecho con ❤️ por <a href="https://www.linkedin.com/company/dial-studio/">DIAL Studio</a> para
  la comunidad Odoo de El Salvador.
</p>
