import json
from unittest.mock import patch, MagicMock

from odoo.tests import tagged
from odoo.exceptions import UserError

from .common import L10nSvDteTestBase


def mock_mh_ok(sello='SELLO_OK'):
    return {
        'status': 'OK',
        'body': {'selloRecibido': sello, 'codigoMsg': '001'},
    }


def mock_mh_rejected(codigo='007', descripcion='NIT inválido'):
    return {
        'status': 'ERROR',
        'body': {'codigoMsg': codigo, 'descripcionMsg': descripcion},
    }


@tagged('post_install', '-at_install', 'l10n_sv_dte', 'l10n_sv_dte_flow')
class TestL10nSvDteFlow(L10nSvDteTestBase):

    def test_01_full_happy_path(self):
        inv = self._create_invoice()
        inv.action_generate_dte_json()
        self.assertEqual(inv.l10n_sv_dte_state, 'json_generated')
        inv.action_sign_dte()
        self.assertEqual(inv.l10n_sv_dte_state, 'signed')
        self.assertTrue(inv.l10n_sv_dte_signed and len(inv.l10n_sv_dte_signed.split('.')) == 3)
        with patch.object(self.env['l10n_sv.api'].sudo().__class__, '_send_dte',
                          return_value=mock_mh_ok('SELLO_HAPPY')):
            inv.action_send_dte()
        self.assertEqual(inv.l10n_sv_dte_state, 'processed')
        self.assertEqual(inv.l10n_sv_dte_sello_recepcion, 'SELLO_HAPPY')
        self.assertEqual(inv.l10n_sv_dte_send_attempts, 1)
        self.assertIsNotNone(inv.l10n_sv_dte_qr_url)
        self.assertIsNotNone(inv.l10n_sv_dte_qr_image)
        log = self.env['l10n_sv.dte.log'].search([('move_id', '=', inv.id)])
        self.assertEqual(len(log), 1)
        self.assertTrue(log[0].success)

    def test_02_rejected_state_on_mh_error(self):
        inv = self._create_invoice()
        inv.action_generate_dte_json()
        inv.action_sign_dte()
        with patch.object(self.env['l10n_sv.api'].sudo().__class__, '_send_dte',
                          return_value=mock_mh_rejected()):
            inv.action_send_dte()
        self.assertEqual(inv.l10n_sv_dte_state, 'rejected')
        self.assertIn('NIT inválido', inv.l10n_sv_dte_last_error)
        self.assertEqual(inv.l10n_sv_dte_send_attempts, 1)
        log = self.env['l10n_sv.dte.log'].search([('move_id', '=', inv.id)])
        self.assertEqual(len(log), 1)
        self.assertFalse(log[0].success)

    def test_03_action_resend_after_rejected(self):
        inv = self._create_invoice()
        inv.action_generate_dte_json()
        inv.action_sign_dte()
        with patch.object(self.env['l10n_sv.api'].sudo().__class__, '_send_dte',
                          side_effect=[mock_mh_rejected(), mock_mh_ok('SELLO_RESEND')]):
            inv.action_send_dte()
            self.assertEqual(inv.l10n_sv_dte_state, 'rejected')
            inv.action_resend_dte()
        self.assertEqual(inv.l10n_sv_dte_state, 'processed')
        self.assertEqual(inv.l10n_sv_dte_sello_recepcion, 'SELLO_RESEND')
        self.assertEqual(inv.l10n_sv_dte_send_attempts, 2)

    def test_04_action_resend_rejects_after_5_attempts(self):
        inv = self._create_invoice()
        inv.write({'l10n_sv_dte_state': 'rejected', 'l10n_sv_dte_send_attempts': 5})
        with self.assertRaises(UserError):
            inv.action_resend_dte()

    def test_05_action_resend_rejects_for_processed_dte(self):
        inv = self._create_invoice()
        inv.write({'l10n_sv_dte_state': 'processed'})
        with self.assertRaises(UserError):
            inv.action_resend_dte()

    def test_06_action_resend_clears_contingencia_flag(self):
        inv = self._create_invoice()
        inv.write({
            'l10n_sv_dte_state': 'contingencia',
            'l10n_sv_dte_contingencia': True,
            'l10n_sv_dte_send_attempts': 0,
            'l10n_sv_dte_signed': 'h.p.s',
        })
        with patch.object(self.env['l10n_sv.api'].sudo().__class__, '_send_dte',
                          return_value=mock_mh_ok('SELLO_CONT')):
            inv.action_resend_dte()
        self.assertFalse(inv.l10n_sv_dte_contingencia)

    def test_07_action_send_marks_contingencia_without_sending(self):
        inv = self._create_invoice()
        inv.write({'l10n_sv_dte_contingencia': True})
        inv.action_generate_dte_json()
        inv.action_sign_dte()
        inv.action_send_dte()
        self.assertEqual(inv.l10n_sv_dte_state, 'contingencia')
        self.assertFalse(inv.l10n_sv_dte_sello_recepcion)

    def test_08_action_reset_to_draft_clears_artifacts(self):
        inv = self._create_invoice()
        inv.action_generate_dte_json()
        inv.action_sign_dte()
        inv.action_reset_to_draft()
        self.assertEqual(inv.l10n_sv_dte_state, 'draft')
        self.assertFalse(inv.l10n_sv_dte_json)
        self.assertFalse(inv.l10n_sv_dte_signed)

    def test_09_action_reset_rejects_for_processed(self):
        inv = self._create_invoice()
        inv.write({'l10n_sv_dte_state': 'processed'})
        with self.assertRaises(UserError):
            inv.action_reset_to_draft()

    def test_10_action_invalidate_full_flow(self):
        inv = self._create_invoice()
        inv.write({
            'l10n_sv_dte_state': 'processed',
            'l10n_sv_dte_sello_recepcion': 'SELLO_INV',
            'l10n_sv_dte_codigo_generacion': 'ABCD-1234',
        })
        with patch.object(self.env['l10n_sv.api'].sudo().__class__, '_invalidate_dte',
                          return_value={'status': 'OK', 'body': {'estado': 'PROCESADO'}}):
            inv.action_invalidate_dte()
        self.assertEqual(inv.l10n_sv_dte_state, 'invalidated')
        self.assertIsNotNone(inv.l10n_sv_dte_invalidated_at)
        log = self.env['l10n_sv.dte.log'].search([
            ('move_id', '=', inv.id), ('operation', '=', 'invalidate'),
        ])
        self.assertEqual(len(log), 1)
        self.assertTrue(log[0].success)

    def test_11_action_invalidate_requires_sello(self):
        inv = self._create_invoice()
        with self.assertRaises(UserError):
            inv.action_invalidate_dte()

    def test_12_action_send_rejects_when_already_processed(self):
        inv = self._create_invoice()
        inv.write({'l10n_sv_dte_state': 'processed', 'l10n_sv_dte_sello_recepcion': 'X'})
        with self.assertRaises(UserError):
            inv.action_send_dte()

    def test_13_wizard_batch_sends(self):
        invs = [self._create_invoice() for _ in range(3)]
        for inv in invs:
            inv.action_generate_dte_json()
            inv.action_sign_dte()
        with patch.object(self.env['l10n_sv.api'].sudo().__class__, '_send_dte',
                          return_value=mock_mh_ok('WIZARD')):
            wizard = self.env['l10n_sv.dte.send.wizard'].create({
                'move_ids': [(6, 0, [i.id for i in invs])],
            })
            wizard.action_send()
        self.assertEqual(wizard.success_count, 3)
        self.assertEqual(wizard.failed_count, 0)
        for inv in invs:
            inv.invalidate_recordset()
            self.assertEqual(inv.l10n_sv_dte_state, 'processed')

    def test_14_wizard_skips_processed_and_invalidated(self):
        inv_pending = self._create_invoice()
        inv_pending.action_generate_dte_json()
        inv_pending.action_sign_dte()
        inv_processed = self._create_invoice()
        inv_processed.write({
            'l10n_sv_dte_state': 'processed',
            'l10n_sv_dte_sello_recepcion': 'X',
        })
        with patch.object(self.env['l10n_sv.api'].sudo().__class__, '_send_dte',
                          return_value=mock_mh_ok('WIZARD2')):
            wizard = self.env['l10n_sv.dte.send.wizard'].create({
                'move_ids': [(6, 0, [inv_pending.id, inv_processed.id])],
            })
            wizard.action_send()
        self.assertEqual(wizard.success_count, 2)
        self.assertEqual(wizard.failed_count, 0)

    def test_15_send_attempt_logged_with_is_automatic(self):
        inv = self._create_invoice()
        inv.write({
            'l10n_sv_dte_state': 'contingencia',
            'l10n_sv_dte_contingencia': True,
            'l10n_sv_dte_send_attempts': 0,
            'l10n_sv_dte_signed': 'h.p.s',
        })
        with patch.object(self.env['l10n_sv.api'].sudo().__class__, '_send_dte',
                          return_value=mock_mh_ok('CRON')):
            self.env['l10n_sv.api'].cron_process_contingencia()
        log = self.env['l10n_sv.dte.log'].search([
            ('move_id', '=', inv.id),
        ])
        self.assertGreaterEqual(len(log), 1)
        self.assertTrue(log[0].is_automatic)

    def test_16_qr_regeneration(self):
        inv = self._create_invoice()
        inv.write({
            'l10n_sv_dte_state': 'processed',
            'l10n_sv_dte_codigo_generacion': 'TEST-UUID',
            'l10n_sv_dte_sello_recepcion': 'REGEN_SELLO',
        })
        inv.action_regenerate_qr()
        self.assertIn('REGEN_SELLO', inv.l10n_sv_dte_qr_url)
        self.assertIn('TEST-UUID', inv.l10n_sv_dte_qr_url)
        self.assertIsNotNone(inv.l10n_sv_dte_qr_image)

    def test_17_qr_regenerate_rejects_non_processed(self):
        inv = self._create_invoice()
        inv.action_generate_dte_json()
        with self.assertRaises(UserError):
            inv.action_regenerate_qr()
