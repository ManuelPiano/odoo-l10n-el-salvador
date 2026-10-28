from odoo import models, fields

class ResCountryState(models.Model):
    _inherit = 'res.country.state'

    # Código de 2 dígitos del MH (ej: '05')
    l10n_sv_code = fields.Char(string='Código Departamento MH', size=2)

class L10nSvMunicipio(models.Model):
    _name = 'l10n_sv.municipio'
    _description = 'Distritos de El Salvador (CAT-008) con su municipio (CAT-013)'
    _order = 'code'

    name = fields.Char(string='Nombre Distrito', required=True)
    active = fields.Boolean(default=True)
    code = fields.Char(string='Código Departamento + Distrito MH', size=4, required=True)
    municipio_mh = fields.Char(
        string='Código Municipio MH (CAT-013)',
        size=2,
        help='Código del municipio vigente (división territorial 2024) que exige el MH en la dirección del DTE.',
    )
    distrito_mh = fields.Char(
        string='Código Distrito MH (CAT-013)',
        size=2,
        help='Código del distrito vigente (división territorial 2024) que exige el MH en la dirección del DTE.',
    )
    state_id = fields.Many2one(
        'res.country.state', 
        string='Departamento', 
        domain="[('country_id.code', '=', 'SV')]", 
        required=True
    )