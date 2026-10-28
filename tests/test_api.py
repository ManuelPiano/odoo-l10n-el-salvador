import json
from unittest.mock import patch, MagicMock

from odoo.tests import tagged

from .common import L10nSvDteTestBase


@tagged('post_install', '-at_install', 'l10n_sv_dte', 'l10n_sv_dte_api')
class TestL10nSvApi(L10nSvDteTestBase):

    def setUp(self):
        super().setUp()
        self.api = self.env['l10n_sv.api'].sudo()
        self.ICP = self.env['ir.config_parameter'].sudo()
        self.ICP.set_param('l10n_sv.api_user_%d' % self.company.id, 'testuser')
        self.ICP.set_param('l10n_sv.api_password_%d' % self.company.id, 'testpass')
        self.api._cache_set_token(self.company, 'TEST_TOKEN')

    def _mock_response(self, status_code=200, json_body=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_body or {}
        resp.text = json.dumps(json_body or {})
        return resp

    def test_01_get_base_url_test_ambiente(self):
        self.company.write({'l10n_sv_ambiente': '00'})
        url = self.api._get_base_url('00')
        self.assertEqual(url, 'https://apitest.dtes.mh.gob.sv')

    def test_02_get_base_url_production_ambiente(self):
        self.company.write({'l10n_sv_ambiente': '01'})
        url = self.api._get_base_url('01')
        self.assertEqual(url, 'https://api.dtes.mh.gob.sv')

    def test_03_get_base_url_arg_overrides_company(self):
        self.company.write({'l10n_sv_ambiente': '01'})
        url = self.api._get_base_url('00')
        self.assertEqual(url, 'https://apitest.dtes.mh.gob.sv')

    def test_04_authenticate_caches_token(self):
        self.api._cache_set_token(self.company, 'EXISTING_TOKEN')
        with patch('requests.post') as mock_post:
            token = self.api._authenticate(company=self.company)
        self.assertEqual(token, 'EXISTING_TOKEN')
        mock_post.assert_not_called()

    def test_05_authenticate_calls_endpoint_when_no_cache(self):
        self.api._cache_clear_token(self.company)
        with patch('requests.post', return_value=self._mock_response(200, {
            'status': 'OK', 'body': {'token': 'NEW_TOKEN_123'},
        })) as mock_post:
            token = self.api._authenticate(company=self.company, force_refresh=True)
            self.assertEqual(token, 'NEW_TOKEN_123')
            self.assertEqual(mock_post.call_count, 1)
            url_called = mock_post.call_args[0][0]
            self.assertIn('/seguridad/auth', url_called)

    def test_06_token_cleared_on_401(self):
        self.api._cache_set_token(self.company, 'STALE_TOKEN')
        with patch('requests.post', return_value=self._mock_response(
            401, {'status': 'ERROR', 'body': {'message': 'expired'}},
        )):
            self.api._send_dte(signed_jws='h.p.s', tipo_dte='01', company=self.company)
        self.assertIsNone(self.api._cache_get_token(self.company))
        with patch('requests.post', return_value=self._mock_response(
            200, {'status': 'OK', 'body': {'token': 'FRESH_TOKEN'}},
        )):
            self.assertEqual(self.api._authenticate(company=self.company), 'FRESH_TOKEN')

    def test_07_send_dte_posts_to_receptordte_endpoint(self):
        jws = 'header.payload.sig'
        with patch('requests.post', return_value=self._mock_response(200, {
            'status': 'OK', 'body': {'selloRecibido': 'SELLO_X'},
        })) as mock_post:
            response = self.api._send_dte(signed_jws=jws, tipo_dte='01', company=self.company)
            self.assertEqual(response['status'], 'OK')
            url_called = mock_post.call_args[0][0]
            self.assertIn('/seguridad/receptordte', url_called)
            body_sent = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
            self.assertEqual(body_sent['tipoDte'], '01')

    def test_08_invalidate_dte_posts_to_anulardte_endpoint(self):
        with patch('requests.post', return_value=self._mock_response(200, {
            'status': 'OK', 'body': {'estado': 'PROCESADO'},
        })) as mock_post:
            response = self.api._invalidate_dte(signed_jws='h.p.s', company=self.company)
            self.assertEqual(response['status'], 'OK')
            url_called = mock_post.call_args[0][0]
            self.assertIn('/seguridad/anulardte', url_called)

    def test_09_contingencia_posts_to_contingencia_endpoint(self):
        with patch('requests.post', return_value=self._mock_response(200, {
            'status': 'OK', 'body': {'estado': 'RECIBIDO'},
        })) as mock_post:
            self.api._send_contingencia(
                signed_jws='h.p.s', id_envio=1,
                company=self.company,
            )
            url_called = mock_post.call_args[0][0]
            self.assertIn('/seguridad/contingencia', url_called)

    def test_10_dte_version_map(self):
        self.assertEqual(self.api._get_dte_version('01'), 2)
        self.assertEqual(self.api._get_dte_version('03'), 4)
        self.assertEqual(self.api._get_dte_version('05'), 4)
        self.assertEqual(self.api._get_dte_version('07'), 2)
        self.assertEqual(self.api._get_dte_version('11'), 3)

    def test_11_cron_process_contingencia_skips_over_max_attempts(self):
        Move = self.env['account.move']
        inv = self._create_invoice()
        inv.write({
            'l10n_sv_dte_state': 'contingencia',
            'l10n_sv_dte_contingencia': True,
            'l10n_sv_dte_send_attempts': 5,
        })
        self.api.cron_process_contingencia()
        inv.invalidate_recordset()
        self.assertEqual(inv.l10n_sv_dte_state, 'contingencia')
        self.assertFalse(inv.l10n_sv_dte_contingencia is False,
                         'No debe modificar moves con 5+ intentos')

    def test_12_cron_process_contingencia_processes_eligible_moves(self):
        inv = self._create_invoice()
        inv.write({
            'l10n_sv_dte_state': 'contingencia',
            'l10n_sv_dte_contingencia': True,
            'l10n_sv_dte_send_attempts': 0,
            'l10n_sv_dte_signed': 'h.p.s',
        })
        with patch.object(self.api.__class__, '_send_dte', return_value={
            'status': 'OK', 'body': {'selloRecibido': 'CRON_SELLO'},
        }):
            self.api.cron_process_contingencia()
        inv.invalidate_recordset()
        self.assertEqual(inv.l10n_sv_dte_state, 'processed')
        self.assertEqual(inv.l10n_sv_dte_sello_recepcion, 'CRON_SELLO')
        log = self.env['l10n_sv.dte.log'].search([
            ('move_id', '=', inv.id), ('is_automatic', '=', True),
        ])
        self.assertEqual(len(log), 1)
        self.assertTrue(log[0].success)
