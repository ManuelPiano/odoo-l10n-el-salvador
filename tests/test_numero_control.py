import re
import uuid

from odoo.tests import tagged

from .common import L10nSvDteTestBase, TEST_COD_ESTABLE, TEST_COD_PUNTO_VENTA


@tagged('post_install', '-at_install', 'l10n_sv_dte', 'l10n_sv_dte_ids')
class TestL10nSvNumeroControl(L10nSvDteTestBase):

    def test_01_codigo_generacion_is_valid_uuid(self):
        invoice = self._create_invoice()
        invoice._ensure_dte_identifiers()
        uuid_value = invoice.l10n_sv_dte_codigo_generacion
        self.assertIsNotNone(uuid_value)
        parsed = uuid.UUID(uuid_value)
        self.assertEqual(str(parsed).upper(), uuid_value)

    def test_02_codigo_generacion_is_unique(self):
        inv1 = self._create_invoice()
        inv2 = self._create_invoice()
        inv1._ensure_dte_identifiers()
        inv2._ensure_dte_identifiers()
        self.assertNotEqual(
            inv1.l10n_sv_dte_codigo_generacion,
            inv2.l10n_sv_dte_codigo_generacion,
        )

    def test_03_codigo_generacion_is_stable_across_calls(self):
        invoice = self._create_invoice()
        invoice._ensure_dte_identifiers()
        original = invoice.l10n_sv_dte_codigo_generacion
        invoice._ensure_dte_identifiers()
        self.assertEqual(invoice.l10n_sv_dte_codigo_generacion, original)

    def test_04_numero_control_format_fcf(self):
        invoice = self._create_invoice(tipo_dte='01')
        invoice._ensure_dte_identifiers()
        nc = invoice.l10n_sv_dte_numero_control
        self.assertTrue(nc.startswith('DTE-01-'), 'NC debe iniciar con DTE-01-')
        self.assertIn(TEST_COD_ESTABLE + TEST_COD_PUNTO_VENTA, nc)
        pattern = r'^DTE-01-[MBSP]\d{3}P\d{3}-\d{15}$'
        self.assertRegex(nc, pattern, 'NC debe coincidir con el formato esperado: %s' % pattern)

    def test_05_numero_control_format_ccf(self):
        invoice = self._create_invoice(tipo_dte='03', partner=self.partner)
        invoice._ensure_dte_identifiers()
        nc = invoice.l10n_sv_dte_numero_control
        self.assertTrue(nc.startswith('DTE-03-'))
        pattern = r'^DTE-03-[MBSP]\d{3}P\d{3}-\d{15}$'
        self.assertRegex(nc, pattern)

    def test_06_numero_control_uses_company_cod_estable(self):
        self.company.write({'l10n_sv_cod_estable_mh': 'S002', 'l10n_sv_cod_punto_venta_mh': 'P005'})
        invoice = self._create_invoice()
        invoice._ensure_dte_identifiers()
        self.assertIn('S002P005', invoice.l10n_sv_dte_numero_control)

    def test_07_numero_control_uses_defaults_when_company_blank(self):
        self.company.write({'l10n_sv_cod_estable_mh': False, 'l10n_sv_cod_punto_venta_mh': False})
        invoice = self._create_invoice()
        invoice._ensure_dte_identifiers()
        self.assertIn('M001P001', invoice.l10n_sv_dte_numero_control)

    def test_08_generate_codigo_generacion_uppercase(self):
        for _ in range(20):
            code = self.env['account.move']._generate_codigo_generacion()
            self.assertEqual(code, code.upper())

    def test_09_generate_numero_control_returns_string(self):
        nc = self.env['account.move']._generate_numero_control('01')
        self.assertIsInstance(nc, str)
        self.assertTrue(re.match(r'^DTE-01-[MBSP]\d{3}P\d{3}-\d{15}$', nc))

    def test_10_numero_control_is_consecutive_per_tipo(self):
        numeros = []
        for _ in range(3):
            invoice = self._create_invoice(tipo_dte='03')
            invoice._ensure_dte_identifiers()
            numeros.append(int(invoice.l10n_sv_dte_numero_control[-15:]))
        self.assertEqual(numeros, [numeros[0], numeros[0] + 1, numeros[0] + 2])

    def test_11_numero_control_sequence_independent_by_tipo_and_establecimiento(self):
        fcf = self._create_invoice(tipo_dte='01')
        fcf._ensure_dte_identifiers()
        ccf = self._create_invoice(tipo_dte='03')
        ccf._ensure_dte_identifiers()
        self.assertEqual(fcf.l10n_sv_dte_numero_control[-15:], '000000000000001')
        self.assertEqual(ccf.l10n_sv_dte_numero_control[-15:], '000000000000001')
        self.company.write({'l10n_sv_cod_estable_mh': 'S002'})
        otro = self._create_invoice(tipo_dte='01')
        otro._ensure_dte_identifiers()
        self.assertEqual(otro.l10n_sv_dte_numero_control, 'DTE-01-S002P001-000000000000001')

    def test_12_numero_control_fits_field(self):
        invoice = self._create_invoice(tipo_dte='03')
        invoice._ensure_dte_identifiers()
        self.assertEqual(len(invoice.l10n_sv_dte_numero_control), 31)
