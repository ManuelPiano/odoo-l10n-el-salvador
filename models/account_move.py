import json
import logging
import uuid
import re
import zlib
from datetime import datetime

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CONDICION_CONTADO = '1'
CONDICION_CREDITO = '2'
CONDICION_ANTICIPO = '3'
UNIDAD_MEDIDA_UNIDAD = 59
PLAZO_DIAS = '01'
TIPO_DOCUMENTO_NIT = '36'
COD_ESTABLE_DEFAULT = 'M001'
TIPOS_NOTA = ('05', '06')
TIPOS_DOCUMENTO_AJUSTABLE = ('03', '07')
TIPO_GENERACION_ELECTRONICO = 2
COD_PUNTO_VENTA_DEFAULT = 'P001'
SV_TZ = 'America/El_Salvador'

L10N_SV_DTE_PROTECTED_FIELDS = frozenset({
    'l10n_sv_dte_state',
    'l10n_sv_dte_sello_recepcion',
    'l10n_sv_dte_codigo_generacion',
    'l10n_sv_dte_numero_control',
    'l10n_sv_dte_json',
    'l10n_sv_dte_signed',
    'l10n_sv_dte_response',
    'l10n_sv_dte_send_attempts',
    'l10n_sv_dte_last_attempt_at',
    'l10n_sv_dte_last_error',
    'l10n_sv_dte_state_changed_at',
    'l10n_sv_dte_invalidated_at',
    'l10n_sv_dte_qr_url',
    'l10n_sv_dte_qr_image',
})

DTE_VERSION_MAP = {
    '01': 2,
    '03': 4,
    '04': 4,
    '05': 4,
    '06': 4,
    '07': 2,
    '08': 2,
    '09': 2,
    '11': 3,
    '14': 2,
    '15': 2,
}
INVALIDACION_VERSION = 3
CONTINGENCIA_VERSION = 4


class AccountMove(models.Model):
    _inherit = 'account.move'

    l10n_sv_dte_tipo_doc = fields.Selection([
        ('01', 'Factura de Consumidor Final (FCF)'),
        ('03', 'Comprobante de Crédito Fiscal (CCF)'),
        ('05', 'Nota de Crédito (NC)'),
        ('06', 'Nota de Débito (ND)'),
        ('14', 'Factura de Sujeto Excluido (FSE)'),
    ], string='Tipo de Documento DTE', help='Tipo de documento electrónico homologado por el MH')

    l10n_sv_dte_condicion_operacion = fields.Selection([
        ('1', 'Contado'),
        ('2', 'Crédito'),
    ], string='Condición de la Operación', default=CONDICION_CONTADO)

    l10n_sv_dte_codigo_generacion = fields.Char(
        string='Código de Generación (UUID)',
        readonly=True, copy=False, size=36,
    )
    l10n_sv_dte_numero_control = fields.Char(
        string='Número de Control',
        readonly=True, copy=False, size=31,
    )
    l10n_sv_dte_sello_recepcion = fields.Char(
        string='Sello de Recepción MH',
        readonly=True, copy=False, size=40,
    )

    l10n_sv_dte_state = fields.Selection([
        ('draft', 'Borrador'),
        ('json_generated', 'JSON Generado'),
        ('signed', 'Firmado'),
        ('sent', 'Enviado'),
        ('processed', 'Procesado por MH'),
        ('rejected', 'Rechazado por MH'),
        ('contingencia', 'En Contingencia'),
        ('invalidating', 'Invalidando'),
        ('invalidated', 'Invalidado por MH'),
    ], string='Estado DTE', default='draft', readonly=True, copy=False,
        tracking=True)

    l10n_sv_dte_json = fields.Text(
        string='JSON DTE (crudo)',
        readonly=True, copy=False,
        help='JSON del DTE generado, antes de firmar. Se usa para re-firma y auditoría.',
    )
    l10n_sv_dte_signed = fields.Text(
        string='JWS Firmado',
        readonly=True, copy=False,
        help='JWS en formato compacto enviado al MH (header.payload.signature).',
    )
    l10n_sv_dte_response = fields.Text(
        string='Respuesta MH',
        readonly=True, copy=False,
        help='Última respuesta JSON del Ministerio de Hacienda.',
    )
    l10n_sv_dte_contingencia = fields.Boolean(
        string='Marcar para contingencia',
        help='Si está activo, el DTE se almacena localmente y se transmite cuando el servicio del MH esté disponible.',
    )
    l10n_sv_dte_tipo_contingencia = fields.Selection([
        ('1', 'Falla de internet'),
        ('2', 'Servicio del MH no disponible'),
        ('3', 'MH rechaza transmisión'),
        ('4', 'Falla del sistema del emisor'),
        ('5', 'Otra'),
    ], string='Tipo de Contingencia')

    l10n_sv_dte_documento_relacionado_ids = fields.One2many(
        'account.move', 'reversed_entry_id',
        string='Documentos Relacionados',
    )

    l10n_sv_dte_observaciones = fields.Text(
        string='Observaciones DTE',
        help='Observaciones que se incluirán en la sección extension del DTE.',
    )
    l10n_sv_dte_forma_pago_id = fields.Many2one(
        'l10n_sv.forma_pago',
        string='Forma de Pago (CAT-017)',
        default=lambda self: self._default_forma_pago(),
        help='Forma de pago predominante para esta operación (CAT-017).',
    )
    l10n_sv_dte_num_pago_electronico = fields.Char(
        string='Número de Pago Electrónico',
        size=100,
        help='Código de pago electrónico generado por la plataforma de pagos (opcional).',
    )

    l10n_sv_dte_send_attempts = fields.Integer(
        string='Intentos de Envío',
        default=0, copy=False, readonly=True,
        help='Número de veces que se ha intentado enviar este DTE al MH.',
    )
    l10n_sv_dte_last_attempt_at = fields.Datetime(
        string='Último Intento',
        copy=False, readonly=True,
    )
    l10n_sv_dte_last_error = fields.Text(
        string='Último Error',
        copy=False, readonly=True,
        help='Mensaje del último error de envío o invalidación.',
    )
    l10n_sv_dte_state_changed_at = fields.Datetime(
        string='Último Cambio de Estado',
        copy=False, readonly=True,
    )
    l10n_sv_dte_invalidated_at = fields.Datetime(
        string='Fecha de Invalidación',
        copy=False, readonly=True,
    )
    l10n_sv_dte_log_ids = fields.One2many(
        'l10n_sv.dte.log', 'move_id',
        string='Bitácora DTE',
        readonly=True,
    )
    l10n_sv_dte_log_count = fields.Integer(
        string='# Bitácora', compute='_compute_l10n_sv_dte_log_count',
    )

    l10n_sv_dte_qr_url = fields.Char(
        string='URL del Código QR',
        readonly=True, copy=False,
    )
    l10n_sv_dte_qr_image = fields.Text(
        string='SVG del Código QR',
        readonly=True, copy=False,
        help='Código QR en formato SVG generado al procesarse el DTE. '
             'Se incrusta en el reporte QWeb del DTE.',
    )

    def write(self, vals):
        if not self.env.su and L10N_SV_DTE_PROTECTED_FIELDS.intersection(vals):
            raise UserError('Los campos del DTE solo se modifican mediante las acciones del flujo DTE.')
        return super().write(vals)

    def _l10n_sv_write(self, vals):
        self.check_access('write')
        return self.sudo().write(vals)

    @api.depends('l10n_sv_dte_log_ids')
    def _compute_l10n_sv_dte_log_count(self):
        for move in self:
            move.l10n_sv_dte_log_count = len(move.l10n_sv_dte_log_ids)

    @api.model
    def _generate_codigo_generacion(self):
        return str(uuid.uuid4()).upper()

    @api.model
    def _get_numero_control_sequence(self, company, tipo_dte, cod_estable, cod_punto_venta):
        code = 'l10n_sv_dte.numero_control.%s.%s%s' % (tipo_dte, cod_estable, cod_punto_venta)
        self.env.cr.execute(
            'SELECT pg_advisory_xact_lock(%s)', [zlib.crc32(('%s:%s' % (company.id, code)).encode())],
        )
        Sequence = self.env['ir.sequence'].sudo()
        sequence = Sequence.search([('code', '=', code), ('company_id', '=', company.id)], limit=1)
        if not sequence:
            sequence = Sequence.create({
                'name': 'Número de control DTE %s %s-%s' % (tipo_dte, cod_estable, cod_punto_venta),
                'code': code,
                'company_id': company.id,
                'implementation': 'no_gap',
                'padding': 15,
                'number_next': 1,
                'number_increment': 1,
            })
        return sequence

    @api.model
    def _generate_numero_control(self, tipo_dte, cod_estable=COD_ESTABLE_DEFAULT, cod_punto_venta=COD_PUNTO_VENTA_DEFAULT, company=None):
        company = company or self.env.company
        sequence = self._get_numero_control_sequence(company, tipo_dte, cod_estable, cod_punto_venta)
        return 'DTE-%s-%s%s-%s' % (tipo_dte, cod_estable, cod_punto_venta, sequence.next_by_id())

    def _ensure_dte_identifiers(self):
        self.ensure_one()
        if not self.l10n_sv_dte_tipo_doc:
            return False
        vals = {}
        if not self.l10n_sv_dte_codigo_generacion:
            vals['l10n_sv_dte_codigo_generacion'] = self._generate_codigo_generacion()
        if not self.l10n_sv_dte_numero_control:
            company = self.company_id
            cod_estable = company.l10n_sv_cod_estable_mh or COD_ESTABLE_DEFAULT
            cod_punto_venta = company.l10n_sv_cod_punto_venta_mh or COD_PUNTO_VENTA_DEFAULT
            vals['l10n_sv_dte_numero_control'] = self._generate_numero_control(
                self.l10n_sv_dte_tipo_doc, cod_estable, cod_punto_venta, company=company,
            )
        if vals:
            self._l10n_sv_write(vals)
        return True

    def _validate_dte_basic(self):
        self.ensure_one()
        if not self.l10n_sv_dte_tipo_doc:
            raise UserError('Debe seleccionar el Tipo de Documento DTE antes de generar el JSON.')
        tipo = self.l10n_sv_dte_tipo_doc
        company, partner = self.company_id, self.partner_id
        errores = []
        if not company.l10n_sv_cod_actividad_id:
            errores.append('Empresa: falta la actividad económica (CAT-019).')
        if not company.l10n_sv_telefono or len(company.l10n_sv_telefono) < 8:
            errores.append('Empresa: falta el teléfono (mínimo 8 caracteres).')
        if not company.l10n_sv_correo or len(company.l10n_sv_correo) < 6:
            errores.append('Empresa: falta el correo electrónico.')
        if not self._l10n_sv_direccion(company):
            errores.append('Empresa: falta departamento, municipio/distrito MH (CAT-012/013) o dirección.')
        if tipo in ('03', '05', '06'):
            if not partner.l10n_sv_nit or not partner.l10n_sv_nrc:
                errores.append('Cliente: para CCF/NC/ND debe tener NIT y NRC.')
            if not partner.l10n_sv_cod_actividad_id:
                errores.append('Cliente: para CCF/NC/ND debe tener actividad económica (CAT-019).')
            if not self._l10n_sv_direccion(partner):
                errores.append('Cliente: falta departamento, municipio/distrito MH (CAT-012/013) o dirección.')
        if tipo in TIPOS_NOTA:
            origen = self._l10n_sv_documento_origen()
            if not origen:
                errores.append(
                    'Nota de crédito/débito: debe vincularse al documento que ajusta '
                    '(factura rectificada o de origen del débito).'
                )
            elif origen.l10n_sv_dte_tipo_doc not in TIPOS_DOCUMENTO_AJUSTABLE:
                errores.append('Nota de crédito/débito: solo puede ajustar un CCF (03) o comprobante de retención (07).')
            elif not (origen.l10n_sv_dte_codigo_generacion and origen.l10n_sv_dte_sello_recepcion):
                errores.append('Nota de crédito/débito: el documento de origen %s aún no fue procesado por el MH.' % origen.name)
        if tipo == '01' and not partner.l10n_sv_nit and not partner.l10n_sv_num_documento:
            errores.append('Cliente: para Factura de Consumidor Final debe tener NIT o número de documento (DUI/Pasaporte).')
        if errores:
            raise UserError('No se puede generar el DTE:\n- %s' % '\n- '.join(errores))

    @api.model
    def _default_forma_pago(self):
        forma = self.env['l10n_sv.forma_pago'].search([('code', '=', '01')], limit=1)
        return forma.id if forma else False

    @api.model
    def _l10n_sv_digits(self, value):
        return re.sub(r'[^0-9]', '', value or '')

    @api.model
    def _l10n_sv_or_none(self, value, min_length=1):
        value = (value or '').strip()
        return value if len(value) >= min_length else None

    @api.model
    def _l10n_sv_direccion(self, record):
        municipio = record.l10n_sv_municipio_id
        departamento = record.state_id.l10n_sv_code or municipio.state_id.l10n_sv_code
        if not (departamento and municipio.municipio_mh and municipio.distrito_mh and record.street):
            return None
        return {
            'departamento': departamento,
            'municipio': municipio.municipio_mh,
            'distrito': municipio.distrito_mh,
            'complemento': record.street[:200],
        }

    def _get_dte_line_tributos(self, line):
        tributos = []
        for tax in line.tax_ids:
            tributo = tax.l10n_sv_tributo_id
            if not tributo:
                continue
            if tax.amount_type == 'percent':
                valor = round(line.price_subtotal * (tax.amount / 100.0), 2)
            else:
                tax_data = tax.compute_all(
                    line.price_unit, currency=line.currency_id, quantity=line.quantity,
                    product=line.product_id, partner=line.partner_id,
                )
                if tax_data['taxes']:
                    valor = round(abs(tax_data['taxes'][0]['amount']), 2)
                else:
                    valor = 0.0
            tributos.append({
                'codigo': tributo.code,
                'descripcion': tributo.name,
                'valor': abs(valor),
            })
        return tributos

    def _l10n_sv_documento_origen(self):
        if self.l10n_sv_dte_tipo_doc == '05':
            return self.reversed_entry_id
        if self.l10n_sv_dte_tipo_doc == '06':
            return self.debit_origin_id
        return self.browse()

    def _build_cuerpo_documento(self):
        tipo = self.l10n_sv_dte_tipo_doc
        iva_incluido = tipo == '01'
        es_nota = tipo in TIPOS_NOTA
        documento_origen = self._l10n_sv_documento_origen().l10n_sv_dte_codigo_generacion if es_nota else None
        cuerpo = []
        resumen = {
            'totalNoSuj': 0.0,
            'totalExenta': 0.0,
            'totalGravada': 0.0,
            'totalNoGravado': 0.0,
            'montoTotalOperacion': 0.0,
            'tributos': {},
            'totalIva': 0.0,
        }
        for idx, line in enumerate(self.invoice_line_ids.filtered(lambda l: l.display_type == 'product'), start=1):
            price_unit = round(line.price_unit, 2)
            discount_pct = line.discount or 0.0
            descuento = round(price_unit * line.quantity * (discount_pct / 100.0), 2)
            gravada = round(line.price_subtotal, 2)
            tributos = self._get_dte_line_tributos(line)
            iva_linea = sum(t['valor'] for t in tributos if t['codigo'] == '20')
            if iva_incluido or es_nota:
                tributos = [t for t in tributos if t['codigo'] != '20']
                resumen['totalIva'] += iva_linea
            if iva_incluido:
                gravada = round(line.price_total, 2)
                if line.quantity and discount_pct < 100:
                    price_unit = round(line.price_total / line.quantity / (1 - discount_pct / 100.0), 2)
                descuento = round(price_unit * line.quantity - gravada, 2) if discount_pct else 0.0
            item = {
                'numItem': idx,
                'tipoItem': 2 if line.product_id.type == 'service' else 1,
                'numeroDocumento': documento_origen,
                'cantidad': line.quantity,
                'codigo': self._l10n_sv_or_none((line.product_id.default_code or '')[:25]),
                'codTributo': None,
                'uniMedida': UNIDAD_MEDIDA_UNIDAD,
                'descripcion': (line.name or line.product_id.display_name or '')[:1500],
                'precioUni': price_unit,
                'montoDescu': max(descuento, 0.0),
                'ventaNoSuj': 0.0,
                'ventaExenta': 0.0,
                'ventaGravada': gravada,
                'tributos': [t['codigo'] for t in tributos] or None,
                'psv': 0.0,
                'noGravado': 0.0,
            }
            if iva_incluido:
                item['ivaItem'] = round(iva_linea, 2)
            if es_nota:
                del item['psv']
                item.update({'ivaPerci': 0.0, 'totalIva': round(iva_linea, 2), 'ivaRete': 0.0})
            cuerpo.append(item)
            resumen['totalGravada'] += gravada
            resumen['montoTotalOperacion'] += line.price_total
            for tr in tributos:
                agg = resumen['tributos'].setdefault(
                    tr['codigo'], {'codigo': tr['codigo'], 'descripcion': tr['descripcion'], 'valor': 0.0},
                )
                agg['valor'] += tr['valor']
        return cuerpo, resumen

    def _build_pagos(self):
        condicion = self.l10n_sv_dte_condicion_operacion or CONDICION_CONTADO
        forma_codigo = self.l10n_sv_dte_forma_pago_id.code if self.l10n_sv_dte_forma_pago_id else '01'
        referencia = self._l10n_sv_or_none(self.l10n_sv_dte_num_pago_electronico)
        total = round(self.amount_total, 2)

        def pago(monto, dias=None):
            return {
                'codigo': forma_codigo,
                'montoPago': monto,
                'referencia': referencia,
                'plazo': PLAZO_DIAS if dias else None,
                'periodo': dias or None,
            }

        if condicion == CONDICION_CONTADO:
            return [pago(total)]
        fecha_base = self.invoice_date or fields.Date.context_today(self)
        cuotas = self.line_ids.filtered(lambda l: l.display_type == 'payment_term').sorted(
            lambda l: (l.date_maturity or fecha_base, l.id),
        )
        if not cuotas:
            return [pago(total)]
        pagos = [
            pago(round(abs(cuota.amount_currency), 2), max(((cuota.date_maturity or fecha_base) - fecha_base).days, 0))
            for cuota in cuotas
        ]
        if abs(sum(p['montoPago'] for p in pagos) - total) > 0.001:
            pagos[-1]['montoPago'] = round(total - sum(p['montoPago'] for p in pagos[:-1]), 2)
        return pagos

    def _build_resumen(self, resumen):
        tipo = self.l10n_sv_dte_tipo_doc
        total_gravada = round(resumen['totalGravada'], 2)
        total_exenta = round(resumen['totalExenta'], 2)
        total_no_suj = round(resumen['totalNoSuj'], 2)
        sub_total_ventas = round(total_gravada + total_exenta + total_no_suj, 2)
        tributos_out = [
            {'codigo': t['codigo'], 'descripcion': t['descripcion'], 'valor': round(t['valor'], 2)}
            for t in resumen['tributos'].values()
        ]
        monto_total_operacion = round(resumen['montoTotalOperacion'], 2)
        resumen_out = {
            'totalNoSuj': total_no_suj,
            'totalExenta': total_exenta,
            'totalGravada': total_gravada,
            'subTotalVentas': sub_total_ventas,
            'descuNoSuj': 0.0,
            'descuExenta': 0.0,
            'descuGravada': 0.0,
            'porcentajeDescuento': 0.0,
            'totalDescu': 0.0,
            'tributos': tributos_out or None,
            'subTotal': sub_total_ventas,
            'ivaRete': 0.0,
            'montoTotalOperacion': monto_total_operacion,
            'totalNoGravado': round(resumen['totalNoGravado'], 2),
            'totalPagar': monto_total_operacion,
            'totalLetras': self._num_to_words_es(monto_total_operacion),
            'saldoFavor': 0.0,
            'condicionOperacion': int(self.l10n_sv_dte_condicion_operacion or CONDICION_CONTADO),
            'pagos': self._build_pagos(),
            'numPagoElectronico': self._l10n_sv_or_none(self.l10n_sv_dte_num_pago_electronico),
            'observaciones': self._l10n_sv_or_none((self.l10n_sv_dte_observaciones or '')[:3000]),
        }
        if tipo in TIPOS_NOTA:
            return self._build_resumen_nota(resumen_out, resumen)
        if tipo == '01':
            resumen_out['totalIva'] = round(resumen['totalIva'], 2)
        else:
            resumen_out['ivaPerci'] = 0.0
        return resumen_out

    def _build_resumen_nota(self, resumen_out, resumen):
        claves = [
            'totalNoSuj', 'totalExenta', 'totalGravada', 'subTotalVentas', 'totalDescu', 'tributos',
            'ivaRete', 'montoTotalOperacion', 'totalNoGravado', 'totalPagar', 'totalLetras',
            'condicionOperacion', 'observaciones',
        ]
        if self.l10n_sv_dte_tipo_doc == '06':
            claves.append('numPagoElectronico')
        nota = {clave: resumen_out[clave] for clave in claves}
        nota.update({
            'ivaPerci': 0.0,
            'totalIva': round(resumen['totalIva'], 2),
            'codigoRetencionMH': None,
        })
        return nota

    def _build_documento_relacionado(self):
        if self.l10n_sv_dte_tipo_doc not in TIPOS_NOTA:
            return None
        origen = self._l10n_sv_documento_origen()
        return [{
            'tipoDocumento': origen.l10n_sv_dte_tipo_doc,
            'tipoGeneracion': TIPO_GENERACION_ELECTRONICO,
            'numeroDocumento': origen.l10n_sv_dte_codigo_generacion,
            'fechaEmision': fields.Date.to_string(origen.invoice_date),
        }]

    def _build_emisor(self):
        company = self.company_id
        emisor = {
            'nit': self._l10n_sv_digits(company.l10n_sv_nit),
            'nrc': self._l10n_sv_digits(company.l10n_sv_nrc),
            'nombre': company.name,
            'codActividad': company.l10n_sv_cod_actividad_id.code,
            'descActividad': (company.l10n_sv_desc_actividad or company.l10n_sv_cod_actividad_id.description or '')[:150],
            'nombreComercial': self._l10n_sv_or_none(company.l10n_sv_nombre_comercial),
            'direccion': self._l10n_sv_direccion(company),
            'telefono': company.l10n_sv_telefono,
            'correo': company.l10n_sv_correo,
            'codEstable': company.l10n_sv_cod_estable_mh or COD_ESTABLE_DEFAULT,
            'codPuntoVenta': company.l10n_sv_cod_punto_venta_mh or COD_PUNTO_VENTA_DEFAULT,
        }
        if self.l10n_sv_dte_tipo_doc in TIPOS_NOTA:
            del emisor['codEstable'], emisor['codPuntoVenta']
        return emisor

    def _build_receptor(self):
        partner = self.partner_id
        actividad = partner.l10n_sv_cod_actividad_id
        nrc = self._l10n_sv_or_none(self._l10n_sv_digits(partner.l10n_sv_nrc), 2)
        telefono = self._l10n_sv_or_none(partner.phone, 8)
        correo = self._l10n_sv_or_none(partner.email, 6)
        if self.l10n_sv_dte_tipo_doc == '01':
            if partner.l10n_sv_nit:
                tipo_documento, num_documento = TIPO_DOCUMENTO_NIT, self._l10n_sv_digits(partner.l10n_sv_nit)
            else:
                tipo_documento = partner.l10n_sv_tipo_documento_id.code or None
                num_documento = self._l10n_sv_or_none(partner.l10n_sv_num_documento)
            return {
                'tipoDocumento': tipo_documento,
                'numDocumento': num_documento,
                'nrc': nrc,
                'nombre': self._l10n_sv_or_none(partner.name),
                'codActividad': actividad.code or None,
                'descActividad': self._l10n_sv_or_none((actividad.description or '')[:150], 5),
                'direccion': self._l10n_sv_direccion(partner),
                'telefono': telefono,
                'correo': correo,
            }
        if self.l10n_sv_dte_tipo_doc in TIPOS_NOTA:
            return {
                'tipoDocumento': TIPO_DOCUMENTO_NIT,
                'numDocumento': self._l10n_sv_digits(partner.l10n_sv_nit),
                'nrc': nrc,
                'nombre': partner.name,
                'codActividad': actividad.code,
                'descActividad': (actividad.description or '')[:150],
                'nombreComercial': self._l10n_sv_or_none(partner.l10n_sv_nombre_comercial),
                'direccion': self._l10n_sv_direccion(partner),
                'telefono': telefono,
                'correo': correo,
            }
        return {
            'nit': self._l10n_sv_digits(partner.l10n_sv_nit),
            'nrc': nrc,
            'nombre': partner.name,
            'codActividad': actividad.code,
            'descActividad': (actividad.description or '')[:150],
            'nombreComercial': self._l10n_sv_or_none(partner.l10n_sv_nombre_comercial),
            'direccion': self._l10n_sv_direccion(partner),
            'telefono': telefono,
            'correo': correo,
        }

    def _build_identificacion(self):
        contingencia = self.l10n_sv_dte_contingencia and self.l10n_sv_dte_tipo_contingencia
        ahora = fields.Datetime.context_timestamp(self.with_context(tz=SV_TZ), fields.Datetime.now())
        identificacion = {
            'version': DTE_VERSION_MAP.get(self.l10n_sv_dte_tipo_doc, 1),
            'ambiente': self.company_id.l10n_sv_ambiente or '00',
            'tipoDte': self.l10n_sv_dte_tipo_doc,
            'numeroControl': self.l10n_sv_dte_numero_control,
            'codigoGeneracion': self.l10n_sv_dte_codigo_generacion,
            'tipoModelo': 2 if contingencia else 1,
            'tipoOperacion': 2 if contingencia else 1,
            'tipoContingencia': int(self.l10n_sv_dte_tipo_contingencia) if contingencia else None,
            'motivoContin': None,
            'fecEmi': fields.Date.to_string(self.invoice_date or ahora.date()),
            'horEmi': ahora.strftime('%H:%M:%S'),
            'tipoMoneda': self.currency_id.name or 'USD',
        }
        if self.l10n_sv_dte_tipo_doc in TIPOS_NOTA:
            identificacion['fusion'] = None
        return identificacion

    def _num_to_words_es(self, amount):
        if amount is None:
            return 'CERO DÓLARES CON CERO CENTAVOS'
        try:
            amount = round(float(amount), 2)
        except (TypeError, ValueError):
            return 'CERO DÓLARES CON CERO CENTAVOS'
        entero, centavos = int(amount), int(round((amount - int(amount)) * 100))
        return '%s DÓLARES CON %02d/100 USD' % (self._int_to_words_es(entero).upper(), centavos)

    def _int_to_words_es(self, n):
        if n == 0:
            return 'cero'
        if n == 100:
            return 'cien'
        unidades = ['', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve']
        teens = ['diez', 'once', 'doce', 'trece', 'catorce', 'quince', 'dieciséis',
                 'diecisiete', 'dieciocho', 'diecinueve']
        decenas = ['', '', 'veinte', 'treinta', 'cuarenta', 'cincuenta',
                   'sesenta', 'setenta', 'ochenta', 'noventa']
        cientos = ['', 'ciento', 'doscientos', 'trescientos', 'cuatrocientos',
                   'quinientos', 'seiscientos', 'setecientos', 'ochocientos', 'novecientos']

        def under1000(x):
            if x == 0:
                return ''
            if x < 10:
                return unidades[x]
            if x < 20:
                return teens[x - 10]
            if x < 100:
                d, u = divmod(x, 10)
                if d == 2 and u:
                    return 'venti' + unidades[u]
                return decenas[d] + ('' if u == 0 else ' y ' + unidades[u])
            c, r = divmod(x, 100)
            base = 'ciento' if c == 1 else cientos[c]
            return base + ('' if r == 0 else ' ' + under1000(r))

        if n < 1000:
            return under1000(n)
        if n < 1_000_000:
            miles, r = divmod(n, 1000)
            head = 'mil' if miles == 1 else under1000(miles) + ' mil'
            return head + ('' if r == 0 else ' ' + under1000(r))
        millones, r = divmod(n, 1_000_000)
        head = 'un millón' if millones == 1 else under1000(millones) + ' millones'
        return head + ('' if r == 0 else ' ' + self._int_to_words_es(r))

    def action_generate_dte_json(self):
        self.ensure_one()
        self._validate_dte_basic()
        self._ensure_dte_identifiers()
        cuerpo_documento, resumen = self._build_cuerpo_documento()
        dte_payload = {
            'identificacion': self._build_identificacion(),
            'documentoRelacionado': self._build_documento_relacionado(),
            'emisor': self._build_emisor(),
            'receptor': self._build_receptor(),
            'otrosDocumentos': None,
            'ventaTercero': None,
            'cuerpoDocumento': cuerpo_documento,
            'resumen': self._build_resumen(resumen),
            'apendice': None,
        }
        if self.l10n_sv_dte_tipo_doc in TIPOS_NOTA:
            del dte_payload['otrosDocumentos']
        self.env['l10n_sv.dte.schema']._validate(dte_payload)
        _logger.info('DTE generado: %s', self.l10n_sv_dte_numero_control)
        self._l10n_sv_write({
            'l10n_sv_dte_state': 'json_generated',
            'l10n_sv_dte_json': json.dumps(dte_payload, ensure_ascii=False, indent=2),
        })
        return dte_payload

    def action_sign_dte(self):
        self.ensure_one()
        if not self.l10n_sv_dte_json:
            payload = self.action_generate_dte_json()
        else:
            payload = json.loads(self.l10n_sv_dte_json)
            self.env['l10n_sv.dte.schema']._validate(payload)

        signer = self.env['l10n_sv.signer'].sudo()
        jws = signer._sign_and_store(self, payload)

        self._l10n_sv_write({
            'l10n_sv_dte_signed': jws,
            'l10n_sv_dte_state': 'signed',
        })
        _logger.info('DTE firmado: %s', self.l10n_sv_dte_numero_control)
        return True

    def _write_dte_state(self, new_state, extra=None):
        self.ensure_one()
        vals = {
            'l10n_sv_dte_state': new_state,
            'l10n_sv_dte_state_changed_at': fields.Datetime.now(),
        }
        if extra:
            vals.update(extra)
        self._l10n_sv_write(vals)
        return True

    def _log_dte_attempt(self, operation, success, response=None, error_message=None,
                         status_code=None, response_code=None, sello_recepcion=None,
                         is_automatic=False, response_body=None):
        self.ensure_one()
        self.env['l10n_sv.dte.log'].sudo().create({
            'move_id': self.id,
            'operation': operation,
            'attempt_number': self.l10n_sv_dte_send_attempts + (0 if operation == 'invalidate' else 1),
            'success': bool(success),
            'status_code': status_code or '',
            'response_code': response_code or '',
            'sello_recepcion': sello_recepcion or '',
            'response_body': response_body or (json.dumps(response, ensure_ascii=False, indent=2) if response else ''),
            'error_message': error_message or '',
            'is_automatic': is_automatic,
        })

    def _compute_qr_url(self):
        self.ensure_one()
        nit = re.sub(r'[^0-9]', '', self.company_id.l10n_sv_nit or '')
        fecha = fields.Date.to_string(self.invoice_date) if self.invoice_date else fields.Date.to_string(fields.Date.today())
        total = round(self.amount_total, 2)
        iva_monto = round(total - self.amount_untaxed, 2)
        from urllib.parse import urlencode
        params = urlencode({
            'nit': nit,
            'codigoGeneracion': self.l10n_sv_dte_codigo_generacion or '',
            'fechaEmision': fecha,
            'montoTotalOperacion': '%0.2f' % total,
            'montoIVA': '%0.2f' % iva_monto,
            'numeroControl': self.l10n_sv_dte_numero_control or '',
            'selloRecibido': self.l10n_sv_dte_sello_recepcion or '',
        })
        return 'https://portaldgii.mh.gob.sv/consulta/QR?%s' % params

    def _generate_qr_image(self):
        self.ensure_one()
        try:
            import qrcode
            from qrcode.image.svg import SvgPathImage
        except ImportError:
            _logger.warning(
                'No se pudo generar el QR: la librería "qrcode" no está instalada '
                '(pip install qrcode). DTE=%s',
                self.l10n_sv_dte_numero_control,
            )
            return None
        url = self._compute_qr_url()
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(image_factory=SvgPathImage)
        svg_bytes = img.to_string(encoding='utf-8')
        return url, svg_bytes

    def action_regenerate_qr(self):
        self.ensure_one()
        if self.l10n_sv_dte_state != 'processed':
            raise UserError(
                'Solo se puede generar el QR para DTEs en estado "Procesado por MH". '
                'Estado actual: %s' % self.l10n_sv_dte_state,
            )
        result = self._generate_qr_image()
        if not result:
            raise UserError(
                'No se pudo generar el QR. Verifique que la librería "qrcode" esté '
                'instalada en el entorno de Odoo (pip install qrcode).'
            )
        url, svg_bytes = result
        self._l10n_sv_write({
            'l10n_sv_dte_qr_url': url,
            'l10n_sv_dte_qr_image': svg_bytes,
        })
        _logger.info('QR regenerado para DTE %s', self.l10n_sv_dte_numero_control)
        return True

    def get_qr_data_url(self):
        self.ensure_one()
        if not self.l10n_sv_dte_qr_image:
            return ''
        import base64
        b64 = base64.b64encode(self.l10n_sv_dte_qr_image.encode('utf-8')).decode('ascii')
        return 'data:image/svg+xml;base64,%s' % b64

    def action_send_dte(self, is_automatic=False):
        self.ensure_one()
        if not self.l10n_sv_dte_signed:
            self.action_sign_dte()
        if self.l10n_sv_dte_state == 'processed' or self.l10n_sv_dte_sello_recepcion:
            raise UserError('Este DTE ya fue procesado por el MH (sello: %s).' % self.l10n_sv_dte_sello_recepcion)
        if self.l10n_sv_dte_state == 'invalidated':
            raise UserError('Este DTE ya fue invalidado por el MH.')
        if not self.l10n_sv_dte_contingencia:
            self._write_dte_state('sent', {
                'l10n_sv_dte_send_attempts': self.l10n_sv_dte_send_attempts + 1,
                'l10n_sv_dte_last_attempt_at': fields.Datetime.now(),
            })
            api = self.env['l10n_sv.api'].sudo()
            try:
                response = api._send_dte(
                    signed_jws=self.l10n_sv_dte_signed,
                    tipo_dte=self.l10n_sv_dte_tipo_doc,
                    company=self.company_id,
                )
            except Exception as e:
                _logger.exception('Error comunicando con el MH al enviar %s', self.l10n_sv_dte_numero_control)
                self._log_dte_attempt(
                    operation='send' if not is_automatic else 'contingencia',
                    success=False,
                    error_message=str(e),
                    is_automatic=is_automatic,
                )
                if is_automatic:
                    self._write_dte_state('contingencia', {
                        'l10n_sv_dte_contingencia': True,
                        'l10n_sv_dte_last_error': str(e),
                    })
                else:
                    self._write_dte_state('rejected', {'l10n_sv_dte_last_error': str(e)})
                return self._l10n_sv_error_notification(str(e))
            body = (response or {}).get('body') if isinstance(response, dict) else None
            sello = (body or {}).get('selloRecibido') or (body or {}).get('selloRecepcion') if isinstance(body, dict) else None
            response_code = (body or {}).get('codigoMsg') or (body or {}).get('codigo') if isinstance(body, dict) else None
            status = (response or {}).get('status') if isinstance(response, dict) else None
            if status == 'OK' and sello:
                self._log_dte_attempt(
                    operation='send',
                    success=True,
                    response=response,
                    status_code=str(response.get('statusCode')) if isinstance(response, dict) else '',
                    response_code=response_code or '',
                    sello_recepcion=sello,
                    is_automatic=is_automatic,
                )
                self._write_dte_state('processed', {
                    'l10n_sv_dte_sello_recepcion': sello,
                    'l10n_sv_dte_last_error': False,
                })
                qr_result = self._generate_qr_image()
                if qr_result:
                    url, svg_bytes = qr_result
                    self._l10n_sv_write({
                        'l10n_sv_dte_qr_url': url,
                        'l10n_sv_dte_qr_image': svg_bytes,
                    })
                _logger.info('DTE PROCESADO por MH: %s (sello=%s)', self.l10n_sv_dte_numero_control, sello)
            else:
                error_msg = (body or {}).get('descripcionMsg') or (body or {}).get('observaciones') if isinstance(body, dict) else None
                self._log_dte_attempt(
                    operation='send',
                    success=False,
                    response=response,
                    error_message=error_msg or 'Rechazado por el MH',
                    status_code=str(response.get('statusCode')) if isinstance(response, dict) else '',
                    response_code=response_code or '',
                    is_automatic=is_automatic,
                )
                self._write_dte_state('rejected', {'l10n_sv_dte_last_error': error_msg or 'Rechazado por el MH'})
                _logger.warning('DTE RECHAZADO por MH: %s - %s', self.l10n_sv_dte_numero_control, response)
        else:
            self._log_dte_attempt(
                operation='contingencia',
                success=True,
                error_message='Marcado para contingencia; el cron reintentará cuando haya servicio del MH.',
                is_automatic=False,
            )
            self._write_dte_state('contingencia')
            _logger.info('DTE marcado para contingencia: %s', self.l10n_sv_dte_numero_control)
        return True

    def action_resend_dte(self):
        self.ensure_one()
        if self.l10n_sv_dte_sello_recepcion:
            raise UserError('Este DTE tiene sello de recepción del MH y no puede reenviarse.')
        if self.l10n_sv_dte_state not in ('rejected', 'contingencia'):
            raise UserError(
                'Solo se pueden reenviar DTEs en estado Rechazado o Contingencia. '
                'Estado actual: %s' % self.l10n_sv_dte_state,
            )
        if self.l10n_sv_dte_send_attempts >= 5:
            raise UserError(
                'Este DTE ya alcanzó el máximo de 5 intentos de envío al MH. '
                'Revise la configuración o contacte a soporte antes de reintentar.',
            )
        if self.l10n_sv_dte_state == 'contingencia':
            self._l10n_sv_write({'l10n_sv_dte_contingencia': False})
        return self.action_send_dte()

    def action_reset_to_draft(self):
        self.ensure_one()
        if self.l10n_sv_dte_state == 'processed' or self.l10n_sv_dte_sello_recepcion:
            raise UserError(
                'No se puede reiniciar un DTE ya procesado por el MH. '
                'Si necesita corregirlo, invalídelo primero y luego emita uno nuevo.',
            )
        if self.l10n_sv_dte_state == 'invalidated':
            raise UserError('Este DTE ya fue invalidado por el MH y no puede reiniciarse.')
        return self._l10n_sv_write({
            'l10n_sv_dte_state': 'draft',
            'l10n_sv_dte_state_changed_at': fields.Datetime.now(),
            'l10n_sv_dte_json': False,
            'l10n_sv_dte_signed': False,
            'l10n_sv_dte_response': False,
            'l10n_sv_dte_last_error': False,
            'l10n_sv_dte_contingencia': False,
            'l10n_sv_dte_tipo_contingencia': False,
        })

    def action_invalidate_dte(self):
        self.ensure_one()
        if not self.l10n_sv_dte_sello_recepcion:
            raise UserError('Solo se pueden invalidar DTEs que ya fueron procesados por el MH (con sello de recepción).')
        if not self.l10n_sv_dte_codigo_generacion:
            raise UserError('El DTE no tiene código de generación. No se puede invalidar.')

        self._write_dte_state('invalidating')

        invalidacion = {
            'identificacion': {
                'version': INVALIDACION_VERSION,
                'ambiente': self.company_id.l10n_sv_ambiente or '00',
                'codigoGeneracion': self.l10n_sv_dte_codigo_generacion,
                'fecAnula': fields.Date.to_string(fields.Date.today()),
                'horAnula': datetime.now().strftime('%H:%M:%S'),
            },
            'emisor': {
                'nit': re.sub(r'[^0-9]', '', self.company_id.l10n_sv_nit or ''),
                'nombre': self.company_id.name,
                'tipoEstablecimiento': self.company_id.l10n_sv_tipo_establecimiento_id.code or '01',
                'codEstableMH': self.company_id.l10n_sv_cod_estable_mh or '',
                'codPuntoVentaMH': self.company_id.l10n_sv_cod_punto_venta_mh or '',
            },
            'documento': {
                'tipoDte': self.l10n_sv_dte_tipo_doc,
                'codigoGeneracion': self.l10n_sv_dte_codigo_generacion,
                'selloRecibido': self.l10n_sv_dte_sello_recepcion,
                'numeroControl': self.l10n_sv_dte_numero_control,
                'fecEmi': fields.Date.to_string(self.invoice_date) if self.invoice_date else '',
                'montoIva': 0.0,
                'codigoGeneracionR': None,
            },
            'motivo': {
                'tipoAnulacion': 2,
                'motivoAnulacion': 'Anulación solicitada por el emisor',
                'nombreResponsable': self.company_id.l10n_sv_nombre_comercial or self.company_id.name,
                'tipDocResponsable': '36',
                'numDocResponsable': re.sub(r'[^0-9]', '', self.company_id.l10n_sv_nit or ''),
            },
        }

        signer = self.env['l10n_sv.signer'].sudo()
        nit = self.company_id.l10n_sv_nit_emisor or self.company_id.l10n_sv_nit or ''
        private_key = signer._load_company_private_key(self.company_id)
        jws = signer.sign_dte(invalidacion, private_key, nit)

        api = self.env['l10n_sv.api'].sudo()
        try:
            response = api._invalidate_dte(signed_jws=jws, company=self.company_id)
        except Exception as e:
            _logger.exception('Error comunicando con el MH al invalidar %s', self.l10n_sv_dte_numero_control)
            self._log_dte_attempt(
                operation='invalidate',
                success=False,
                error_message=str(e),
            )
            self._write_dte_state('processed', {'l10n_sv_dte_last_error': str(e)})
            return self._l10n_sv_error_notification(str(e))

        body = (response or {}).get('body') if isinstance(response, dict) else None
        status = (response or {}).get('status') if isinstance(response, dict) else None
        if status == 'OK':
            self._log_dte_attempt(
                operation='invalidate',
                success=True,
                response=response,
                status_code=str(response.get('statusCode')) if isinstance(response, dict) else '',
            )
            self._write_dte_state('invalidated', {
                'l10n_sv_dte_invalidated_at': fields.Datetime.now(),
            })
            _logger.info('DTE INVALIDADO por MH: %s', self.l10n_sv_dte_numero_control)
        else:
            error_msg = (body or {}).get('descripcionMsg') if isinstance(body, dict) else 'Rechazo de invalidación'
            self._log_dte_attempt(
                operation='invalidate',
                success=False,
                response=response,
                error_message=error_msg,
                status_code=str(response.get('statusCode')) if isinstance(response, dict) else '',
            )
            self._write_dte_state('processed', {'l10n_sv_dte_last_error': error_msg})
        return True

    def _l10n_sv_error_notification(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Error de comunicación con el MH',
                'message': message,
                'type': 'danger',
                'sticky': True,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
