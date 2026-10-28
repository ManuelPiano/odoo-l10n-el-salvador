import base64
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged, new_test_user

from .common import L10nSvDteTestBase


@tagged('post_install', '-at_install', 'l10n_sv_dte', 'l10n_sv_dte_security')
class TestL10nSvSecurity(L10nSvDteTestBase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('l10n_sv.api_user_%d' % cls.company.id, 'testuser')
        ICP.set_param('l10n_sv.api_password_%d' % cls.company.id, 'testpass')
        cls.env['l10n_sv.api']._cache_set_token(cls.company, 'CACHED_TOKEN')
        cls.portal = new_test_user(cls.env, login='sv_portal', groups='base.group_portal', company_id=cls.company.id)
        cls.invoicer = new_test_user(
            cls.env, login='sv_invoicer', groups='base.group_user,account.group_account_invoice',
            company_id=cls.company.id,
        )

    def _call_kw(self, user, model, method, args=None, kwargs=None):
        from odoo.api import call_kw
        from odoo.service.model import get_public_method
        records = self.env[model].with_user(user)
        get_public_method(records, method)
        return call_kw(records, method, args or [], kwargs or {})

    def test_01_invoice_lines_reach_cuerpo_documento(self):
        inv = self._create_invoice(tipo_dte='03', precio=100.0)
        payload = inv.action_generate_dte_json()
        self.assertEqual(len(payload['cuerpoDocumento']), 1)
        self.assertAlmostEqual(payload['resumen']['totalPagar'], inv.amount_total, places=2)

    def test_02_connector_methods_not_callable_by_rpc(self):
        for user in (self.portal, self.invoicer):
            for method in ('_authenticate', '_send_dte', '_test_connection', '_get_config'):
                with self.assertRaises(AccessError, msg='%s/%s' % (user.login, method)):
                    self._call_kw(user, 'l10n_sv.api', method)
            with self.assertRaises(AccessError):
                self._call_kw(user, 'res.company', '_get_l10n_sv_api_config', [[self.company.id]])

    def test_03_cron_requires_system(self):
        for user in (self.portal, self.invoicer):
            with self.assertRaises(AccessError):
                self.env['l10n_sv.api'].with_user(user).cron_process_contingencia()
        self.assertTrue(self.env['l10n_sv.api'].cron_process_contingencia())

    def test_04_test_connection_button_requires_system(self):
        with self.assertRaises(AccessError):
            self.company.with_user(self.invoicer).action_test_mh_connection()

    def test_05_certificate_not_readable_by_non_admin(self):
        for user in (self.portal, self.invoicer):
            with self.assertRaises(AccessError):
                self.company.with_user(user).read(['l10n_sv_certificate'])
        attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'res.company'), ('res_id', '=', self.company.id),
            ('res_field', '=', 'l10n_sv_certificate'),
        ])
        self.assertTrue(attachments)
        for user in (self.portal, self.invoicer):
            with self.assertRaises(AccessError):
                attachments.with_user(user).read(['datas'])

    def test_06_invoicer_can_still_sign(self):
        inv = self._create_invoice(tipo_dte='03', precio=50.0).with_user(self.invoicer)
        inv.action_sign_dte()
        self.assertEqual(inv.l10n_sv_dte_state, 'signed')
        self.assertEqual(len(inv.l10n_sv_dte_signed.split('.')), 3)

    def test_07_portal_cannot_touch_catalogs_or_log(self):
        tributo = self.env['l10n_sv.tributo'].search([('code', '=', '20')], limit=1)
        with self.assertRaises(AccessError):
            tributo.with_user(self.portal).read(['name'])
        with self.assertRaises(AccessError):
            tributo.with_user(self.invoicer).write({'name': 'X'})
        inv = self._create_invoice()
        log = self.env['l10n_sv.dte.log'].create({'move_id': inv.id, 'operation': 'send'})
        with self.assertRaises(AccessError):
            log.with_user(self.portal).read(['operation'])
        self.assertTrue(log.with_user(self.invoicer).read(['operation']))
        with self.assertRaises(AccessError):
            log.with_user(self.invoicer).unlink()
        with self.assertRaises(AccessError):
            log.with_user(self.invoicer).write({'success': True})

    def test_08_dte_log_isolated_by_company(self):
        other = self.env['res.company'].create({'name': 'Otra empresa SV'})
        inv = self._create_invoice()
        self.env['l10n_sv.dte.log'].create({'move_id': inv.id, 'operation': 'send'})
        outsider = new_test_user(
            self.env, login='sv_outsider', groups='base.group_user,account.group_account_invoice',
            company_id=other.id, company_ids=[(6, 0, [other.id])],
        )
        logs = self.env['l10n_sv.dte.log'].with_user(outsider).with_context(allowed_company_ids=[other.id])
        self.assertFalse(logs.search([('move_id', '=', inv.id)]))
