# API del Ministerio de Hacienda (MH)

Referencia técnica de la integración con la API REST del MH de El
Salvador. Implementada en `models/l10n_sv_api.py`.

## Endpoints

| Acción | Endpoint | Método |
|--------|----------|--------|
| Autenticación | `/seguridad/auth` | POST |
| Recepción DTE | `/seguridad/receptordte` | POST |
| Invalidación DTE | `/seguridad/anulardte` | POST |
| Contingencia | `/seguridad/contingencia` | POST |

URLs base:

- **Pruebas (ambiente 00)**: `https://apitest.dtes.mh.gob.sv`
- **Producción (ambiente 01)**: `https://api.dtes.mh.gob.sv`

La selección de URL se hace en `l10n_sv_api._get_base_url(ambiente)` que
lee `res.company.l10n_sv_ambiente` (campo de selección `00`/`01`).

## Autenticación

POST a `/seguridad/auth` con body **form-urlencoded**:

```
Content-Type: application/x-www-form-urlencoded

user=<api_user>&pwd=<api_password>
```

Equivalente en curl:

```bash
curl --location 'https://apitest.dtes.mh.gob.sv/seguridad/auth' \
--header 'Content-Type: application/x-www-form-urlencoded' \
--data-urlencode 'user=<api_user>' \
--data-urlencode 'pwd=<api_password>'
```

Respuesta exitosa:

```json
{
  "status": "OK",
  "body": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expiresAt": "2025-01-15T18:00:00Z"
  }
}
```

### Cache del token

- **Almacenamiento**: `ir.config_parameter`, con clave
  `l10n_sv.api_token_<company_id>` y `l10n_sv.api_token_expiry_<company_id>`.
- **TTL efectivo**: 55 minutos (los tokens del MH expiran a los 60
  minutos, refrescamos 5 min antes).
- **Re-uso**: la siguiente llamada dentro del TTL reusa el token.
- **Invalidación automática**: si el MH devuelve HTTP 401, el token
  cacheado se borra y se reintenta una vez con un token fresco.

### Credenciales

Se leen desde `ir.config_parameter` con claves:

- `l10n_sv.api_user_<company_id>` — usuario de la API del MH
- `l10n_sv.api_password_<company_id>` — contraseña de la API

**Nunca** se guardan en `res.company`. Configurar vía shell de Odoo:

```python
env['ir.config_parameter'].sudo().set_param(
    'l10n_sv.api_user_1', '<usuario_mh>',
)
env['ir.config_parameter'].sudo().set_param(
    'l10n_sv.api_password_1', '<password_mh>',
)
```

## Recepción de DTE

POST a `/seguridad/receptordte` con body JSON:

```json
{
  "Content-Type": "application/json",
  "ambiente": "00",
  "idEnvio": 1,
  "version": 1,
  "tipoDte": "01",
  "documento": "<JWS_COMPACT>"
}
```

El `documento` es el JWS firmado en formato compacto
(`header.payload.signature`) generado por `l10n_sv_signer.sign_dte()`.

Respuesta exitosa:

```json
{
  "status": "OK",
  "statusCode": 200,
  "body": {
    "codigoMsg": "001",
    "descripcionMsg": "DTE recibido y procesado",
    "selloRecibido": "2025ABCD1234...",
    "estado": "PROCESADO"
  }
}
```

Respuesta de rechazo:

```json
{
  "status": "ERROR",
  "statusCode": 400,
  "body": {
    "codigoMsg": "007",
    "descripcionMsg": "NIT del receptor inválido",
    "observaciones": []
  }
}
```

El campo `selloRecibido` (a veces `selloRecepcion`) se guarda en
`account.move.l10n_sv_dte_sello_recepcion` y es el identificador único
del DTE en el portal del MH.

## Invalidación de DTE

POST a `/seguridad/anulardte` con body:

```json
{
  "Content-Type": "application/json",
  "ambiente": "00",
  "idEnvio": 1,
  "version": 2,
  "documento": "<JWS_COMPACT>"
}
```

El `documento` es un JWS con un payload de tipo `anulaciondte`:

```json
{
  "identificacion": {
    "version": 2,
    "ambiente": "00",
    "codigoGeneracion": "<UUID>",
    "fecAnula": "2025-01-15",
    "horAnula": "14:30:00"
  },
  "emisor": {
    "nit": "06141406100012",
    "nombre": "Mi Empresa S.A. de C.V.",
    "tipoEstablecimiento": "01",
    "codEstableMH": "0001",
    "codPuntoVentaMH": "0001"
  },
  "documento": {
    "tipoDte": "01",
    "codigoGeneracion": "<UUID>",
    "selloRecibido": "<SELLO>",
    "numeroControl": "DTE-01-00010001-...",
    "fecEmi": "2025-01-15",
    "montoIva": 0.0,
    "codigoGeneracionR": null
  },
  "motivo": {
    "tipoAnulacion": 2,
    "motivoAnulacion": "Anulación solicitada por el emisor",
    "nombreResponsable": "Mi Empresa",
    "tipDocResponsable": "36",
    "numDocResponsable": "06141406100012"
  }
}
```

`tipoAnulacion`:

- `1`: Error en la información del DTE
- `2`: Anulación solicitada por el emisor
- `3`: Otro

## Contingencia

POST a `/seguridad/contingencia` con body:

```json
{
  "Content-Type": "application/json",
  "ambiente": "00",
  "idEnvio": 1,
  "version": 3,
  "documento": "<JWS_COMPACT>"
}
```

Para DTEs marcados con `l10n_sv_dte_contingencia = True` cuando el
servicio del MH está caído. El cron `ir_cron_l10n_sv_dte_contingencia`
re-intenta el envío cada 5 minutos.

## Versión por tipo de DTE

| Código | Tipo | Versión |
|--------|------|---------|
| 01 | Factura de Consumidor Final (FCF) | 1 |
| 03 | Comprobante de Crédito Fiscal (CCF) | 3 |
| 04 | Nota de Remisión | 3 |
| 05 | Nota de Crédito | 3 |
| 06 | Nota de Débito | 3 |
| 07 | Retención | 1 |
| 08 | Liquidación | 1 |
| 09 | Documento Contable de Liquidación | 1 |
| 11 | Factura de Exportación (FEX) | 1 |
| 14 | Factura de Sujeto Excluido (FSE) | 1 |
| 15 | Donación | 1 |

`l10n_sv.api._get_dte_version(tipo_dte)` retorna la versión según esta
tabla, que se inserta en `identificacion.version` del JSON DTE.

## Manejo de errores HTTP

| Código | Significado | Acción del módulo |
|--------|-------------|-------------------|
| 200 | Éxito | Continuar flujo normal |
| 400 | DTE malformado o rechazo de validación | Log + estado `rejected` |
| 401 | Token expirado o inválido | Limpiar cache + reintentar 1 vez |
| 403 | Credenciales no autorizadas | `UserError` con mensaje claro |
| 500 | Error interno del MH | Log + estado `rejected` + registro en bitácora |
| Timeout | MH no responde | Marcar contingencia + reintento en cron |

## Logging

Cada llamada al MH se registra en `l10n_sv.dte.log` con:

- `operation`: `send` / `invalidate` / `contingencia`
- `attempt_number`: número de intento
- `attempt_at`: fecha/hora
- `success`: True/False
- `status_code`: HTTP status
- `response_code`: `codigoMsg` del MH
- `sello_recepcion`: si aplica
- `response_body`: JSON completo del MH
- `error_message`: descripción del error si falló
- `is_automatic`: True si fue disparado por el cron

La bitácora se ve en *Facturación SV → Bitácora DTE* o desde la pestaña
*Facturación Electrónica (DTE)* de la factura con el botón *Ver
bitácora*.

## Probar la conexión

En la ficha de la empresa, botón **"Probar Conexión MH"**. Internamente
llama `l10n_sv.api._test_connection(company=...)` que:

1. Hace `authenticate(force_refresh=True)` con las credenciales cacheadas.
2. Si obtiene token → notificación de éxito.
3. Si falla → `UserError` con diagnóstico.

## Sandbox vs Producción

| Ambiente | URL | ¿DTE real? |
|----------|-----|-----------|
| `00` (Pruebas) | `https://apitest.dtes.mh.gob.sv` | No, son DTEs de prueba |
| `01` (Producción) | `https://api.dtes.mh.gob.sv` | Sí, DTEs con valor fiscal |

> **Importante**: en producción, los DTEs procesados son válidos
> fiscalmente. El ambiente `00` es para integración y pruebas, y los
> DTEs allí no tienen efecto real. Coordinar con el MH el pase a
> producción luego de completar el proceso de certificación.
