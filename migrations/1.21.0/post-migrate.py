import difflib
import logging
import re
import unicodedata

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

REFERENCIAS = (('res_partner', 'l10n_sv_municipio_id'), ('res_company', 'l10n_sv_municipio_id'))


def _norm(nombre):
    nombre = re.sub(r'\(.*?\)', ' ', nombre or '')
    nombre = unicodedata.normalize('NFKD', nombre).encode('ascii', 'ignore').decode().upper()
    return ' '.join(nombre.replace('.', ' ').split())


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    cr.execute("""
        SELECT res_id FROM ir_model_data
        WHERE module = 'l10n_sv_dte' AND model = 'l10n_sv.municipio' AND name LIKE 'mun\\_sv\\_%%'
    """)
    viejos = env['l10n_sv.municipio'].browse([r[0] for r in cr.fetchall()]).exists()
    if not viejos:
        return
    nuevos = env['l10n_sv.municipio'].search([('id', 'not in', viejos.ids)])
    por_depto = {}
    for nuevo in nuevos:
        por_depto.setdefault(nuevo.state_id.id, {})[_norm(nuevo.name)] = nuevo.id
    sin_match = []
    for viejo in viejos:
        candidatos = por_depto.get(viejo.state_id.id, {})
        clave = _norm(viejo.name)
        if clave not in candidatos:
            parecidos = difflib.get_close_matches(clave, list(candidatos), n=1, cutoff=0.85)
            clave = parecidos[0] if parecidos else None
        if clave:
            for tabla, columna in REFERENCIAS:
                cr.execute(
                    'UPDATE %s SET %s = %%s WHERE %s = %%s' % (tabla, columna, columna),
                    (candidatos[clave], viejo.id),
                )
            continue
        referenciado = False
        for tabla, columna in REFERENCIAS:
            cr.execute('SELECT 1 FROM %s WHERE %s = %%s LIMIT 1' % (tabla, columna), (viejo.id,))
            referenciado = referenciado or bool(cr.fetchone())
        if referenciado:
            sin_match.append(viejo.name)
            viejo.active = False
            cr.execute("""
                UPDATE ir_model_data SET noupdate = TRUE
                WHERE module = 'l10n_sv_dte' AND model = 'l10n_sv.municipio' AND res_id = %s
            """, (viejo.id,))
    if sin_match:
        _logger.warning(
            'Distritos antiguos sin equivalente en CAT-008; quedan archivados y los contactos que los usan '
            'deben corregirse a mano: %s', ', '.join(sorted(sin_match)),
        )
