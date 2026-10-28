from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    l10n_sv_nit = fields.Char(string='NIT / DUI', help='Número de Identificación Tributaria o DUI')
    l10n_sv_nrc = fields.Char(string='NRC', help='Número de Registro de Contribuyente')
    l10n_sv_nombre_comercial = fields.Char(string='Nombre Comercial')
    l10n_sv_giro = fields.Char(string='Giro / Actividad Económica')
    l10n_sv_cod_actividad_id = fields.Many2one(
        'l10n_sv.actividad_economica',
        string='Actividad Económica (CAT-019)',
        help='Actividad económica del receptor según catálogo del MH. Obligatoria para CCF/NC/ND.',
    )
    l10n_sv_municipio_id = fields.Many2one(
        'l10n_sv.municipio', string='Municipio MH',
        domain="[('state_id', '=', state_id)]",
    )

    l10n_sv_tipo_documento_id = fields.Many2one(
        'l10n_sv.tipo_documento', string='Tipo de Documento (CAT-022)',
        help='Tipo de documento de identificación del cliente (DUI, NIT, Pasaporte, etc.)',
    )
    l10n_sv_num_documento = fields.Char(
        string='Número de Documento',
        help='Número del documento de identificación. Requerido para FCF cuando no hay NIT.',
    )

    l10n_sv_tipo_contribuyente = fields.Selection([
        ('grande', 'Grande Contribuyente'),
        ('mediano', 'Mediano Contribuyente'),
        ('otros', 'Otros / Pequeño'),
    ], string='Tipo de Contribuyente', default='otros')
