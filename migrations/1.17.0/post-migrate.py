import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'res_company' AND column_name = 'l10n_sv_certificate_id'
    """)
    if not cr.fetchone():
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute('SELECT id, l10n_sv_certificate_id FROM res_company WHERE l10n_sv_certificate_id IS NOT NULL')
    for company_id, attachment_id in cr.fetchall():
        attachment = env['ir.attachment'].browse(attachment_id).exists()
        if not attachment:
            continue
        env['res.company'].browse(company_id).write({
            'l10n_sv_certificate': attachment.datas,
            'l10n_sv_certificate_filename': attachment.name,
        })
        attachment.unlink()
        _logger.info('Certificado MH migrado a campo restringido para la compañía %s', company_id)
    cr.execute('ALTER TABLE res_company DROP COLUMN l10n_sv_certificate_id')
