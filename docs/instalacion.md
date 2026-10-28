# Instalación de l10n_sv_dte

Guía para instalar el módulo en una instancia de Odoo 18.

## 1. Requisitos del entorno

- **Odoo**: 18.0
- **PostgreSQL**: 12 o superior
- **Python**: 3.10 o superior
- **Dependencias Python**:
  - `requests` (HTTP)
  - `cryptography` (parseo de certificado MH + firma RSA)
  - `jsonschema` (validación del DTE contra los esquemas oficiales del MH)
  - `qrcode` (generación de QR en formato SVG, sin necesidad de Pillow)

```bash
pip install requests cryptography qrcode jsonschema
```

- **`wkhtmltopdf`** (opcional, recomendado): para generar PDFs del DTE
  desde el reporte QWeb.

```bash
# Ubuntu / Debian
sudo apt-get install -y wkhtmltopdf

# macOS (Homebrew)
brew install --cask wkhtmltopdf
```

> Si `wkhtmltopdf` no está instalado, el reporte sigue disponible
> como **HTML** desde el menú contextual *Imprimir*.

## 2. Dependencias del módulo

- `base` — modelos base de Odoo (res.partner, res.company, ir.attachment, etc.)
- `account` — modelo `account.move` que se extiende con la pestaña DTE

Ambas vienen con Odoo, no se instalan por separado.

## 3. Instalación

### Desde la interfaz web

1. Copiar el directorio `l10n_sv_dte/` a la carpeta de addons de Odoo
   (por defecto `~/odoo/addons/` o la que indique el parámetro
   `--addons-path` al iniciar el servidor).
2. Reiniciar el servidor de Odoo:

   ```bash
   ./odoo-bin -c odoo.conf -u all
   ```

   o con flag `--update` apuntando al módulo:

   ```bash
   ./odoo-bin -c odoo.conf -i l10n_sv_dte
   ```

3. Activar el modo *Desarrollador* (*Ajustes → Opciones generales*).
4. *Aplicaciones → Actualizar lista de aplicaciones*.
5. Buscar **"El Salvador"** o **"DTE"** e instalar
   *Localización de El Salvador - Facturación Electrónica (DTE)*.

### Verificación de la instalación

- Menú *Facturación SV* debe aparecer en la barra superior con los
  sub-menús *Catálogos MH*, *Bitácora DTE* y *Envío Masivo DTE*.
- En la ficha de la empresa (compañía) debe aparecer la pestaña
  *Facturación Electrónica SV*.

## 4. Configuración inicial

### 4.1 Datos de la empresa

En *Ajustes → Compañías → [Su empresa] → pestaña "Facturación Electrónica SV"*:

| Campo | Descripción | Ejemplo |
|-------|-------------|---------|
| NIT | Número de Identificación Tributaria (sin guiones) | `06141406100012` |
| NRC | Número de Registro de Contribuyente | `1234567` |
| Nombre Comercial | Razón social que aparece en la factura | `Mi Empresa S.A. de C.V.` |
| Giro | Actividad comercial | `Comercio al por mayor` |
| Municipio MH | Municipio homologado por el MH | (catálogo) |
| Actividad Económica (CAT-019) | Código CIIU de la actividad | (catálogo) |
| Tipo de Establecimiento (CAT-009) | Matriz, Sucursal, etc. | `01 - Matriz` |
| Código Establecimiento MH | 4 dígitos, asignado por el MH | `0001` |
| Código Punto de Venta MH | 4 dígitos, asignado por el MH | `0001` |
| Teléfono | Teléfono de contacto en el DTE | `22334455` |
| Correo | Email de contacto en el DTE | `facturacion@empresa.com.sv` |
| Ambiente MH | `00` Pruebas / `01` Producción | `00` |
| Certificado Digital MH | Adjuntar el `.crt` XML del MH | (archivo) |
| NIT Emisor | NIT que se usa como `kid` en la firma JWS | (mismo NIT) |

### 4.2 Credenciales de la API del MH

> Las credenciales **no** se guardan en la ficha de la empresa. Viven en
> `ir.config_parameter` (parámetros del sistema) por seguridad.

Configurar las credenciales que entrega el MH para acceder a su API:

```python
# Desde un shell de Odoo:
env['ir.config_parameter'].sudo().set_param(
    'l10n_sv.api_user_1',  # reemplazar 1 por el ID de la compañía
    'su_usuario_del_mh',
)
env['ir.config_parameter'].sudo().set_param(
    'l10n_sv.api_password_1',
    'su_contraseña_del_mh',
)
```

Para múltiples compañías, usar el sufijo `_<company_id>` en la clave.

### 4.3 Certificado digital

1. Descargar el archivo `.crt` (XML) que entrega el MH tras el proceso de
   certificación.
2. En la ficha de la empresa, campo *Certificado Digital MH* → adjuntar el
   archivo.
3. El módulo parsea el XML en busca de la clave privada embebida
   (`<privateKey><encodied>BASE64_PEM</encodied></privateKey>`).

> El archivo **nunca** debe commitearse al repositorio ni compartirse.

### 4.4 Probar la conexión

En la ficha de la empresa, botón **"Probar Conexión MH"**. Si todo está
correcto, el sistema obtiene un token de autenticación y muestra una
notificación de éxito. Si falla, revisar:

- Ambiente seleccionado (00 o 01)
- URL del servicio (pruebas vs producción)
- Usuario/contraseña de la API del MH
- Conectividad a internet saliente

## 5. Configuración de impuestos

Para que el JSON DTE mapee correctamente los impuestos a tributos del MH
(CAT-015), cada `account.tax` que se use en facturas DTE debe tener
asignado su `l10n_sv_tributo_id` (campo agregado por este módulo).

El módulo instala dos impuestos preconfigurados:

| Impuesto (account.tax) | Tributo MH (CAT-015) |
|------------------------|----------------------|
| IVA 13% (Ventas)       | `20` (IVA 13%)       |
| Retención 1% (Ventas)  | `C5` (Retención 1%)  |

Para agregar otros impuestos, crear el `account.tax` correspondiente
(*Contabilidad → Configuración → Impuestos*) y vincularlo con un registro
de `l10n_sv.tributo` desde el campo `l10n_sv_tributo_id`.

## 6. Datos del cliente

Para que el DTE incluya la información del cliente, en la ficha de cada
contacto:

- `l10n_sv_nit`: NIT o DUI (sin guiones)
- `l10n_sv_nrc`: NRC (obligatorio para CCF, NC y ND)
- `l10n_sv_municipio_id`: municipio del catálogo
- `l10n_sv_tipo_documento_id` + `l10n_sv_num_documento`: para FCF cuando
  el cliente no tiene NIT
- `l10n_sv_giro`: actividad del cliente

## 7. Emisión del primer DTE

1. Crear una factura de cliente (*Facturación → Clientes → Facturas*).
2. En la pestaña *Facturación Electrónica (DTE)*, seleccionar
   *Tipo de Documento DTE* (FCF, CCF, NC, ND, FSE).
3. Seleccionar la *Condición de la Operación* (Contado o Crédito).
4. Botón **1. Generar JSON DTE** → genera el payload conforme al MH.
5. Botón **2. Firmar JWS** → firma con el certificado.
6. Botón **3. Enviar al MH** → transmite y recibe el sello de recepción.
7. Una vez procesado, aparece el código QR y la opción de imprimir el
   DTE en PDF.

## 8. Desinstalación

1. *Aplicaciones* → buscar el módulo → *Desinstalar*.
2. Los modelos de catálogo (municipios, tributos, etc.) se eliminan.
3. Los campos DTE agregados a `account.move` se eliminan (los datos
   quedan como `False` en los registros existentes).
4. **Los JSON DTE, JWS firmados, sellos de recepción y bitácora se
   conservan** en los registros, ya que viven en columnas del propio
   `account.move` o en `l10n_sv.dte.log`. Si se reinstala, vuelven a
   estar visibles.

## 9. Actualización de versión

Al subir de versión (`18.0.1.3.0` → `18.0.1.4.0` etc.):

```bash
./odoo-bin -c odoo.conf -u l10n_sv_dte -d <database>
```

Odoo detecta el cambio de versión en `__manifest__.py` y aplica las
migraciones declaradas en `migrations/` (si las hay). Para esta versión
del módulo no hay script de migración explícito: los nuevos campos se
agregan como columnas con default, y los nuevos modelos se crean vacíos.

> Si vienes de una versión < 1.0.0, consulta la sección
> "Migración" en el README principal.
