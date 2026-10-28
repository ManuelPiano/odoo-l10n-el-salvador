import json
from unittest.mock import patch

from odoo.tests import tagged
from odoo.exceptions import UserError

from .common import L10nSvDteTestBase, TEST_NIT_DIGITS


@tagged('post_install', '-at_install', 'l10n_sv_dte', 'l10n_sv_dte_json')
class TestL10nSvDteJson(L10nSvDteTestBase):

    def test_01_fcf_v1_identificacion(self):
        invoice = self._create_invoice(tipo_dte='01')
        payload = invoice.action_generate_dte_json()
        ident = payload['identificacion']
        self.assertEqual(ident['version'], 2)
        self.assertEqual(ident['tipoDte'], '01')
        self.assertEqual(ident['ambiente'], '00')
        self.assertEqual(ident['tipoMoneda'], 'USD')
        self.assertIn('numeroControl', ident)
        self.assertIn('codigoGeneracion', ident)

    def test_02_ccf_v3_identificacion(self):
        invoice = self._create_invoice(tipo_dte='03', partner=self.partner)
        payload = invoice.action_generate_dte_json()
        ident = payload['identificacion']
        self.assertEqual(ident['version'], 4)
        self.assertEqual(ident['tipoDte'], '03')

    def test_03_emisor_strips_dashes_from_nit(self):
        self.company.write({'l10n_sv_nit': '0614-140610-001-2'})
        invoice = self._create_invoice()
        payload = invoice.action_generate_dte_json()
        self.assertEqual(payload['emisor']['nit'], TEST_NIT_DIGITS)

    def test_04_emisor_direccion_uses_municipio_and_distrito_mh(self):
        invoice = self._create_invoice()
        payload = invoice.action_generate_dte_json()
        direccion = payload['emisor']['direccion']
        self.assertEqual(direccion['departamento'], self.municipio.state_id.l10n_sv_code)
        self.assertEqual(direccion['municipio'], '13')
        self.assertEqual(direccion['distrito'], '01')

    def test_05_cuerpo_documento_has_tributos_for_iva_line(self):
        if not self.iva_13:
            self.skipTest('No se encontró el impuesto IVA 13% mapeado a tributo 20.')
        invoice = self._create_invoice(tipo_dte='03', cantidad=2, precio=100.0)
        payload = invoice.action_generate_dte_json()
        cuerpo = payload['cuerpoDocumento']
        self.assertEqual(len(cuerpo), 1)
        item = cuerpo[0]
        self.assertEqual(item['cantidad'], 2)
        self.assertEqual(item['ventaGravada'], 200.0)
        self.assertEqual(item['tributos'], ['20'])
        iva_t = next(t for t in payload['resumen']['tributos'] if t['codigo'] == '20')
        self.assertAlmostEqual(iva_t['valor'], 26.0, places=2)

    def test_06_cuerpo_documento_fcf_has_numeric_iva_item(self):
        invoice = self._create_invoice(tipo_dte='01')
        payload = invoice.action_generate_dte_json()
        item = payload['cuerpoDocumento'][0]
        self.assertAlmostEqual(item['ivaItem'], 13.0, places=2)

    def test_07_cuerpo_documento_ccf_has_no_iva_item(self):
        if not self.iva_13:
            self.skipTest('No se encontró el impuesto IVA 13% mapeado a tributo 20.')
        invoice = self._create_invoice(tipo_dte='03', partner=self.partner)
        payload = invoice.action_generate_dte_json()
        item = payload['cuerpoDocumento'][0]
        self.assertNotIn('ivaItem', item)

    def test_08_resumen_fcf_uses_total_iva(self):
        if not self.iva_13:
            self.skipTest('No se encontró el impuesto IVA 13% mapeado a tributo 20.')
        invoice = self._create_invoice(cantidad=1, precio=100.0)
        payload = invoice.action_generate_dte_json()
        resumen = payload['resumen']
        self.assertNotIn('ivaPerci', resumen)
        self.assertAlmostEqual(resumen['totalIva'], 13.0, places=2)
        self.assertIsNone(resumen['tributos'])

    def test_09_resumen_ccf_uses_tributos_and_iva_perci(self):
        if not self.iva_13:
            self.skipTest('No se encontró el impuesto IVA 13% mapeado a tributo 20.')
        invoice = self._create_invoice(tipo_dte='03', partner=self.partner)
        payload = invoice.action_generate_dte_json()
        resumen = payload['resumen']
        self.assertEqual(resumen['ivaPerci'], 0.0)
        self.assertNotIn('totalIva', resumen)
        self.assertEqual([t['codigo'] for t in resumen['tributos']], ['20'])

    def test_10_resumen_pagos_contado(self):
        invoice = self._create_invoice(condicion='1', cantidad=1, precio=100.0)
        payload = invoice.action_generate_dte_json()
        resumen = payload['resumen']
        self.assertIn('pagos', resumen)
        self.assertEqual(len(resumen['pagos']), 1)
        self.assertEqual(resumen['pagos'][0]['montoPago'], 113.0)
        self.assertEqual(resumen['pagos'][0]['codigo'], '01')

    def test_11_resumen_total_letras(self):
        invoice = self._create_invoice(cantidad=1, precio=100.0)
        payload = invoice.action_generate_dte_json()
        resumen = payload['resumen']
        self.assertIn('totalLetras', resumen)
        self.assertIn('DÓLARES', resumen['totalLetras'])
        self.assertIn('USD', resumen['totalLetras'])

    def test_12_validate_rejects_ccf_without_nit(self):
        partner_sin_nit = self.env['res.partner'].create({
            'name': 'Sin NIT',
            'l10n_sv_municipio_id': self.municipio.id,
        })
        invoice = self._create_invoice(tipo_dte='03', partner=partner_sin_nit)
        with self.assertRaises(UserError):
            invoice.action_generate_dte_json()

    def test_13_validate_rejects_fcf_without_doc(self):
        partner_sin_doc = self.env['res.partner'].create({
            'name': 'Sin Doc',
            'l10n_sv_municipio_id': self.municipio.id,
        })
        invoice = self._create_invoice(tipo_dte='01', partner=partner_sin_doc)
        with self.assertRaises(UserError):
            invoice.action_generate_dte_json()

    def test_14_observaciones_in_resumen(self):
        invoice = self._create_invoice()
        invoice.write({'l10n_sv_dte_observaciones': 'Cliente retira en tienda'})
        payload = invoice.action_generate_dte_json()
        self.assertNotIn('extension', payload)
        self.assertEqual(payload['resumen']['observaciones'], 'Cliente retira en tienda')

    def test_15_observaciones_null_when_empty(self):
        invoice = self._create_invoice()
        payload = invoice.action_generate_dte_json()
        self.assertIsNone(payload['resumen']['observaciones'])

    def test_16_nc_includes_documento_relacionado(self):
        ref_invoice = self._create_processed_ccf()
        payload = self._create_nota('05', ref_invoice, precio=50.0).action_generate_dte_json()
        rel = payload['documentoRelacionado'][0]
        self.assertEqual(rel['tipoDocumento'], '03')
        self.assertEqual(rel['tipoGeneracion'], 2)
        self.assertEqual(rel['numeroDocumento'], ref_invoice.l10n_sv_dte_codigo_generacion)
        self.assertEqual(rel['fechaEmision'], '2025-01-15')

    def test_17_fcf_does_not_include_documento_relacionado(self):
        invoice = self._create_invoice(tipo_dte='01')
        payload = invoice.action_generate_dte_json()
        self.assertIsNone(payload['documentoRelacionado'])

    def test_18_dte_state_advances_to_json_generated(self):
        invoice = self._create_invoice()
        self.assertEqual(invoice.l10n_sv_dte_state, 'draft')
        invoice.action_generate_dte_json()
        self.assertEqual(invoice.l10n_sv_dte_state, 'json_generated')
        self.assertIsNotNone(invoice.l10n_sv_dte_json)

    def test_19_numero_pago_electronico_in_resumen(self):
        invoice = self._create_invoice()
        invoice.write({'l10n_sv_dte_num_pago_electronico': 'REF-12345'})
        payload = invoice.action_generate_dte_json()
        self.assertEqual(payload['resumen'].get('numPagoElectronico'), 'REF-12345')

    def test_20_credito_pagos_split_by_payment_term(self):
        term = self.env['account.payment.term'].create({
            'name': '30/60',
            'line_ids': [
                (0, 0, {'value': 'percent', 'value_amount': 50.0, 'nb_days': 30}),
                (0, 0, {'value': 'percent', 'value_amount': 50.0, 'nb_days': 60}),
            ],
        })
        invoice = self._create_invoice(condicion='2', cantidad=1, precio=100.0)
        invoice.write({'invoice_payment_term_id': term.id})
        payload = invoice.action_generate_dte_json()
        pagos = payload['resumen']['pagos']
        self.assertEqual(len(pagos), 2)
        total_pagos = sum(p['montoPago'] for p in pagos)
        self.assertAlmostEqual(total_pagos, 113.0, places=2)
        self.assertEqual([p['periodo'] for p in pagos], [30, 60])
        self.assertTrue(all(p['plazo'] == '01' for p in pagos))

    def test_21_credito_pagos_with_fixed_amount_term(self):
        term = self.env['account.payment.term'].create({
            'name': '20 fijo + saldo',
            'line_ids': [
                (0, 0, {'value': 'fixed', 'value_amount': 20.0, 'nb_days': 0}),
                (0, 0, {'value': 'percent', 'value_amount': 100.0, 'nb_days': 45}),
            ],
        })
        invoice = self._create_invoice(condicion='2', cantidad=1, precio=100.0)
        invoice.write({'invoice_payment_term_id': term.id})
        pagos = invoice.action_generate_dte_json()['resumen']['pagos']
        self.assertEqual([p['montoPago'] for p in pagos], [20.0, 93.0])
        self.assertEqual([p['periodo'] for p in pagos], [None, 45])
        self.assertEqual([p['plazo'] for p in pagos], [None, '01'])

    def test_22_credito_without_term_single_payment(self):
        invoice = self._create_invoice(condicion='2', cantidad=1, precio=100.0)
        pagos = invoice.action_generate_dte_json()['resumen']['pagos']
        self.assertEqual(len(pagos), 1)
        self.assertAlmostEqual(pagos[0]['montoPago'], 113.0, places=2)
