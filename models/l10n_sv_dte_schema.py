import json
import logging
from decimal import Decimal

import jsonschema

from odoo import api, models, _
from odoo.exceptions import UserError
from odoo.tools.misc import file_path

_logger = logging.getLogger(__name__)

DTE_SCHEMAS = {
    '01': 'fe-f-v2.json',
    '03': 'fe-ccf-v4.json',
    '05': 'fe-nc-v4.json',
    '06': 'fe-nd-v4.json',
}
MAX_ERRORES_MOSTRADOS = 15

_validators = {}


def _get_validator(tipo_dte):
    if tipo_dte not in _validators:
        with open(file_path('l10n_sv_dte/data/schemas/%s' % DTE_SCHEMAS[tipo_dte]), encoding='utf-8') as f:
            schema = json.load(f, parse_float=Decimal)
        _validators[tipo_dte] = jsonschema.Draft7Validator(schema)
    return _validators[tipo_dte]


class L10nSvDteSchema(models.AbstractModel):
    _name = 'l10n_sv.dte.schema'
    _description = 'Validación de DTE contra los JSON Schema del MH'

    @api.model
    def _get_errors(self, dte_payload):
        tipo_dte = (dte_payload.get('identificacion') or {}).get('tipoDte')
        if tipo_dte not in DTE_SCHEMAS:
            _logger.warning('DTE tipo %s sin esquema JSON incluido; no se valida.', tipo_dte)
            return []
        instancia = json.loads(json.dumps(dte_payload), parse_float=Decimal)
        errores = sorted(_get_validator(tipo_dte).iter_errors(instancia), key=lambda e: list(map(str, e.absolute_path)))
        return ['%s: %s' % ('/'.join(map(str, e.absolute_path)) or '(raíz)', e.message) for e in errores]

    @api.model
    def _validate(self, dte_payload):
        errores = self._get_errors(dte_payload)
        if errores:
            extra = len(errores) - MAX_ERRORES_MOSTRADOS
            detalle = '\n- '.join(errores[:MAX_ERRORES_MOSTRADOS])
            if extra > 0:
                detalle += _('\n- ... y %d error(es) más', extra)
            raise UserError(_('El DTE no cumple el esquema del Ministerio de Hacienda:\n- %s', detalle))
        return True
