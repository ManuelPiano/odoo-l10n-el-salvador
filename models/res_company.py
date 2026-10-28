from odoo import models, fields, api, _
import re

from odoo.exceptions import AccessError, ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_sv_nit = fields.Char(string='NIT')
    l10n_sv_nrc = fields.Char(string='NRC')
    l10n_sv_nombre_comercial = fields.Char(string='Nombre Comercial')
    l10n_sv_giro = fields.Char(string='Giro')
    l10n_sv_telefono = fields.Char(string='Teléfono', help='Teléfono de contacto para el DTE')
    l10n_sv_correo = fields.Char(string='Correo Electrónico', help='Correo de contacto para el DTE')

    l10n_sv_municipio_id = fields.Many2one(
        'l10n_sv.municipio',
        string='Municipio MH',
        help='Seleccione el municipio para la localización de El Salvador'
    )

    l10n_sv_cod_actividad_id = fields.Many2one(
        'l10n_sv.actividad_economica',
        string='Actividad Económica (CAT-019)',
        help='Actividad económica del emisor según catálogo del MH'
    )
    l10n_sv_desc_actividad = fields.Char(
        string='Descripción de Actividad',
        help='Descripción complementaria de la actividad económica'
    )
    l10n_sv_tipo_establecimiento_id = fields.Many2one(
        'l10n_sv.tipo_establecimiento',
        string='Tipo de Establecimiento (CAT-009)',
        help='Tipo de establecimiento del emisor (Matriz, Sucursal, etc.)'
    )
    l10n_sv_cod_estable_mh = fields.Char(
        string='Código Establecimiento MH',
        size=4,
        help='Código del establecimiento: letra del tipo (M matriz, S sucursal, B bodega, P patio) y 3 dígitos. Ej: M001.'
    )
    l10n_sv_cod_punto_venta_mh = fields.Char(
        string='Código Punto de Venta MH',
        size=4,
        help='Código del punto de venta: P y 3 dígitos. Ej: P001.'
    )

    l10n_sv_ambiente = fields.Selection([
        ('00', 'Pruebas (Test)'),
        ('01', 'Producción (Certificación)'),
    ], string='Ambiente MH', default='00', required=True,
        help='Ambiente de la API del Ministerio de Hacienda. Use 00 para pruebas y 01 para producción.')

    l10n_sv_certificate = fields.Binary(
        string='Certificado Digital MH',
        attachment=True,
        groups='base.group_system',
        help='Certificado digital (.crt XML) emitido por el Ministerio de Hacienda para firma de DTE',
    )
    l10n_sv_certificate_filename = fields.Char(
        string='Nombre del certificado',
        groups='base.group_system',
    )

    l10n_sv_nit_emisor = fields.Char(string='NIT Emisor (para autenticación)')

    @api.constrains('l10n_sv_cod_estable_mh', 'l10n_sv_cod_punto_venta_mh')
    def _check_l10n_sv_codigos_establecimiento(self):
        for company in self:
            if company.l10n_sv_cod_estable_mh and not re.fullmatch(r'[MBSP][0-9]{3}', company.l10n_sv_cod_estable_mh):
                raise ValidationError(_('El código de establecimiento debe tener el formato M001, S001, B001 o P001.'))
            if company.l10n_sv_cod_punto_venta_mh and not re.fullmatch(r'P[0-9]{3}', company.l10n_sv_cod_punto_venta_mh):
                raise ValidationError(_('El código de punto de venta debe tener el formato P001.'))

    def _get_l10n_sv_api_config(self):
        """
        Retorna la configuración de la API del MH.
        Las credenciales sensibles se almacenan en ir.config_parameter.
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'ambiente': self.l10n_sv_ambiente or '00',
            'base_url': 'https://apitest.dtes.mh.gob.sv' if self.l10n_sv_ambiente == '00' else 'https://api.dtes.mh.gob.sv',
            'api_user': ICP.get_param('l10n_sv.api_user_%s' % self.id, default=''),
            'api_password': ICP.get_param('l10n_sv.api_password_%s' % self.id, default=''),
            'nit_emisor': self.l10n_sv_nit_emisor or self.l10n_sv_nit or '',
        }

    def action_open_credentials_help(self):
        return {
            'type': 'ir.actions.act_url',
            'url': 'https://www.factura.gob.sv/',
            'target': 'new',
        }

    def action_test_mh_connection(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Solo un administrador puede probar la conexión con el MH.'))
        api = self.env['l10n_sv.api']
        config = self._get_l10n_sv_api_config()

        if not config['api_user'] or not config['api_password']:
            return self._test_connection_notification(
                False,
                _('Faltan credenciales'),
                _('Configure los parámetros del sistema l10n_sv.api_user_%(cid)d y l10n_sv.api_password_%(cid)d antes de probar la conexión.') % {'cid': self.id},
            )

        token = api._authenticate(company=self, force_refresh=True)
        if token:
            return self._test_connection_notification(
                True,
                _('Conexión exitosa'),
                _('Se obtuvo un token válido del Ministerio de Hacienda.'),
            )

        return self._test_connection_notification(
            False,
            _('Conexión Fallida'),
            _('No se pudo autenticar con el MH. Verifique:\n'
              '1) Credenciales correctas en Parámetros del sistema\n'
              '2) NIT del emisor: %(nit)s\n'
              '3) Ambiente: %(amb)s\n'
              '4) URL: %(url)s') % {
                  'nit': config['nit_emisor'] or '(vacío)',
                  'amb': 'Pruebas' if config['ambiente'] == '00' else 'Producción',
                  'url': api._get_base_url(config['ambiente']),
                  },
        )

    def _test_connection_notification(self, success, title, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': 'success' if success else 'danger',
                'sticky': True,
            },
        }
