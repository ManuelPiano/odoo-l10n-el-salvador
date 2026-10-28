import requests
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged, new_test_user

from .common import L10nSvDteTestBase

API_CLASS_PATH = 'odoo.addons.l10n_sv_dte.models.l10n_sv_api.requests.post'


@tagged('post_install', '-at_install', 'l10n_sv_dte', 'l10n_sv_dte_integrity')
class TestL10nSvDteIntegrity(L10nSvDteTestBase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.invoicer = new_test_user(
            cls.env, login='sv_integrity_invoicer', groups='base.group_user,account.group_account_invoice',
            company_id=cls.company.id,
        )
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('l10n_sv.api_user_%d' % cls.company.id, 'testuser')
        ICP.set_param('l10n_sv.api_password_%d' % cls.company.id, 'testpass')
        cls.env['l10n_sv.api']._cache_set_token(cls.company, 'TEST_TOKEN')

    def _api(self):
        return type(self.env['l10n_sv.api'])

    def _signed_invoice(self, **kw):
        inv = self._create_invoice(**kw)
        inv.action_sign_dte()
        return inv

    def test_01_protected_fields_not_writable_by_user(self):
        inv = self._create_invoice(tipo_dte='03').with_user(self.invoicer)
        for vals in (
            {'l10n_sv_dte_state': 'processed'},
            {'l10n_sv_dte_sello_recepcion': 'SELLO-FALSO'},
            {'l10n_sv_dte_numero_control': 'DTE-03-M001P001-000000000000999'},
        ):
            with self.assertRaises(UserError):
                inv.write(vals)
        inv.write({'l10n_sv_dte_observaciones': 'permitido'})

    def test_02_user_can_run_flow_actions(self):
        inv = self._create_invoice(tipo_dte='03').with_user(self.invoicer)
        inv.action_generate_dte_json()
        inv.action_sign_dte()
        self.assertEqual(inv.l10n_sv_dte_state, 'signed')
        self.assertTrue(inv.l10n_sv_dte_numero_control)

    def test_03_discount_counted_once(self):
        inv = self._create_invoice(tipo_dte='03', precio=100.0, descuento=10.0)
        payload = inv.action_generate_dte_json()
        item, resumen = payload['cuerpoDocumento'][0], payload['resumen']
        self.assertEqual(item['ventaGravada'], 90.0)
        self.assertEqual(item['montoDescu'], 10.0)
        self.assertEqual(resumen['totalDescu'], 0.0)
        self.assertEqual(resumen['subTotal'], 90.0)
        tributos = sum(t['valor'] for t in resumen['tributos'])
        self.assertAlmostEqual(resumen['subTotal'] + tributos, resumen['montoTotalOperacion'], places=2)
        self.assertAlmostEqual(resumen['totalPagar'], inv.amount_total, places=2)

    def test_04_fcf_amounts_include_iva(self):
        inv = self._create_invoice(tipo_dte='01', cantidad=2, precio=100.0, descuento=10.0)
        payload = inv.action_generate_dte_json()
        item, resumen = payload['cuerpoDocumento'][0], payload['resumen']
        self.assertEqual(item['precioUni'], 113.0)
        self.assertEqual(item['ventaGravada'], 203.4)
        self.assertEqual(item['montoDescu'], 22.6)
        self.assertAlmostEqual(item['ivaItem'], 23.4, places=2)
        self.assertIsNone(item['tributos'])
        self.assertAlmostEqual(resumen['totalIva'], 23.4, places=2)
        self.assertEqual(resumen['subTotal'], 203.4)
        self.assertAlmostEqual(resumen['totalPagar'], inv.amount_total, places=2)

    def test_05_send_uses_invoice_company(self):
        main = self.env.ref('base.main_company')
        self.company.write({'l10n_sv_ambiente': '01'})
        inv = self._signed_invoice(tipo_dte='03')
        calls = []

        def fake_send(api, signed_jws, tipo_dte, id_envio=1, ambiente=None, company=None):
            calls.append(company)
            return {'status': 'OK', 'body': {'selloRecibido': 'S' * 40}}

        with patch.object(self._api(), '_send_dte', fake_send):
            inv.with_context(allowed_company_ids=[main.id, self.company.id]).action_send_dte()
        self.assertEqual(calls, [self.company])
        self.assertEqual(inv.l10n_sv_dte_state, 'processed')

    def test_06_network_error_persists_log_and_state(self):
        inv = self._signed_invoice(tipo_dte='03')
        with patch(API_CLASS_PATH, side_effect=requests.ConnectionError('MH caído')):
            with self.env.cr.savepoint():
                result = inv.action_send_dte()
        inv.invalidate_recordset()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(inv.l10n_sv_dte_state, 'rejected')
        self.assertEqual(inv.l10n_sv_dte_send_attempts, 1)
        self.assertIn('MH caído', inv.l10n_sv_dte_last_error)
        self.assertEqual(len(inv.l10n_sv_dte_log_ids), 1)

    def test_07_network_error_in_cron_returns_to_contingencia(self):
        inv = self._signed_invoice(tipo_dte='03')
        inv._l10n_sv_write({'l10n_sv_dte_state': 'contingencia'})
        inv.write({'l10n_sv_dte_contingencia': True})
        with patch(API_CLASS_PATH, side_effect=requests.ConnectionError('MH caído')):
            self.env['l10n_sv.api'].cron_process_contingencia()
        self.assertEqual(inv.l10n_sv_dte_state, 'contingencia')
        self.assertTrue(inv.l10n_sv_dte_contingencia)
        self.assertEqual(inv.l10n_sv_dte_send_attempts, 1)
        self.assertTrue(inv.l10n_sv_dte_log_ids.is_automatic)

    def _processed_invoice(self):
        inv = self._signed_invoice(tipo_dte='03')
        with patch.object(self._api(), '_send_dte', return_value={
            'status': 'OK', 'body': {'selloRecibido': 'S' * 40},
        }):
            inv.action_send_dte()
        return inv

    def test_08_rejected_invalidation_keeps_processed(self):
        inv = self._processed_invoice()
        with patch.object(self._api(), '_invalidate_dte', return_value={
            'status': 'ERROR', 'body': {'descripcionMsg': 'Fuera de plazo'},
        }):
            inv.action_invalidate_dte()
        self.assertEqual(inv.l10n_sv_dte_state, 'processed')
        self.assertEqual(inv.l10n_sv_dte_last_error, 'Fuera de plazo')
        with self.assertRaises(UserError):
            inv.action_reset_to_draft()
        with self.assertRaises(UserError):
            inv.action_resend_dte()
        with self.assertRaises(UserError):
            inv.action_send_dte()

    def test_09_network_error_on_invalidation_keeps_processed(self):
        inv = self._processed_invoice()
        with patch(API_CLASS_PATH, side_effect=requests.ConnectionError('MH caído')):
            result = inv.action_invalidate_dte()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(inv.l10n_sv_dte_state, 'processed')
        self.assertTrue(inv.l10n_sv_dte_sello_recepcion)
