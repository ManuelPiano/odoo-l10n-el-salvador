import json

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import L10nSvDteTestBase


@tagged('post_install', '-at_install', 'l10n_sv_dte', 'l10n_sv_dte_schema')
class TestL10nSvDteSchema(L10nSvDteTestBase):

    def _errors(self, payload):
        return self.env['l10n_sv.dte.schema']._get_errors(payload)

    def _credit_term(self):
        return self.env['account.payment.term'].create({
            'name': '30/60',
            'line_ids': [
                (0, 0, {'value': 'percent', 'value_amount': 50.0, 'nb_days': 30}),
                (0, 0, {'value': 'percent', 'value_amount': 50.0, 'nb_days': 60}),
            ],
        })

    def test_01_fcf_matches_schema(self):
        inv = self._create_invoice(tipo_dte='01', cantidad=3, precio=33.33, descuento=5.0)
        self.assertEqual(self._errors(inv.action_generate_dte_json()), [])

    def test_02_ccf_matches_schema(self):
        inv = self._create_invoice(tipo_dte='03', cantidad=2, precio=100.0, descuento=10.0)
        self.assertEqual(self._errors(inv.action_generate_dte_json()), [])

    def test_03_ccf_credit_with_observaciones_matches_schema(self):
        inv = self._create_invoice(tipo_dte='03', condicion='2')
        inv.write({
            'invoice_payment_term_id': self._credit_term().id,
            'l10n_sv_dte_observaciones': 'Entrega en bodega',
            'l10n_sv_dte_num_pago_electronico': 'REF-1',
        })
        self.assertEqual(self._errors(inv.action_generate_dte_json()), [])

    def test_04_fcf_consumer_with_dui_matches_schema(self):
        dui = self.env['l10n_sv.tipo_documento'].search([('code', '=', '13')], limit=1)
        consumer = self.env['res.partner'].create({
            'name': 'Consumidor Final',
            'l10n_sv_tipo_documento_id': dui.id,
            'l10n_sv_num_documento': '01234567-8',
        })
        inv = self._create_invoice(tipo_dte='01', partner=consumer)
        payload = inv.action_generate_dte_json()
        self.assertEqual(self._errors(payload), [])
        self.assertIsNone(payload['receptor']['direccion'])
        self.assertEqual(payload['receptor']['numDocumento'], '01234567-8')

    def test_05_fcf_receptor_with_nit_uses_tipo_36(self):
        receptor = self._create_invoice(tipo_dte='01').action_generate_dte_json()['receptor']
        self.assertEqual(receptor['tipoDocumento'], '36')
        self.assertNotIn('nit', receptor)

    def test_06_invalid_payload_raises(self):
        inv = self._create_invoice(tipo_dte='03')
        payload = inv.action_generate_dte_json()
        payload['emisor']['codEstableMH'] = 'X'
        del payload['resumen']['ivaPerci']
        with self.assertRaises(UserError) as ctx:
            self.env['l10n_sv.dte.schema']._validate(payload)
        self.assertIn('codEstableMH', str(ctx.exception))
        self.assertIn('ivaPerci', str(ctx.exception))

    def test_07_sign_revalidates_stored_json(self):
        inv = self._create_invoice(tipo_dte='03')
        payload = inv.action_generate_dte_json()
        payload['resumen']['totalPagar'] = -1
        inv._l10n_sv_write({'l10n_sv_dte_json': json.dumps(payload)})
        with self.assertRaises(UserError):
            inv.action_sign_dte()
        self.assertEqual(inv.l10n_sv_dte_state, 'json_generated')

    def test_08_generation_blocked_without_distrito(self):
        self.municipio.write({'distrito_mh': False})
        inv = self._create_invoice(tipo_dte='03')
        with self.assertRaises(UserError) as ctx:
            inv.action_generate_dte_json()
        self.assertIn('distrito', str(ctx.exception))
        self.assertEqual(inv.l10n_sv_dte_state, 'draft')

    def test_09_ccf_blocked_without_receptor_actividad(self):
        self.partner.write({'l10n_sv_cod_actividad_id': False})
        with self.assertRaises(UserError):
            self._create_invoice(tipo_dte='03').action_generate_dte_json()

    def test_10_company_codes_must_match_numero_control_format(self):
        with self.assertRaises(ValidationError):
            self.company.write({'l10n_sv_cod_estable_mh': '0001'})
        with self.assertRaises(ValidationError):
            self.company.write({'l10n_sv_cod_punto_venta_mh': '0001'})

    def test_11_catalogo_distritos_oficial(self):
        Distrito = self.env['l10n_sv.municipio'].with_context(active_test=False)
        self.assertEqual(Distrito.search_count([]), 262)
        casos = {
            'distrito_sv_0103': ('Atiquizaya', '13', '03'),
            'distrito_sv_0614': ('San Salvador', '23', '14'),
            'distrito_sv_0511': ('Santa Tecla', '28', '11'),
            'distrito_sv_1121': ('Santiago de María', '24', '21'),
            'distrito_sv_1418': ('Yucuaiquín', '20', '18'),
        }
        for xmlid, (nombre, municipio, distrito) in casos.items():
            registro = self.env.ref('l10n_sv_dte.%s' % xmlid)
            self.assertEqual(
                (registro.name, registro.municipio_mh, registro.distrito_mh),
                (nombre, municipio, distrito),
            )
        sin_codigo = Distrito.search(['|', ('municipio_mh', '=', False), ('distrito_mh', '=', False)])
        self.assertFalse(sin_codigo - self.municipio)

    def test_12_nc_matches_schema(self):
        origen = self._create_processed_ccf()
        nc = self._create_nota('05', origen, precio=33.33, cantidad=3)
        payload = nc.action_generate_dte_json()
        self.assertEqual(self._errors(payload), [])
        self.assertEqual(payload['identificacion']['version'], 4)
        self.assertNotIn('otrosDocumentos', payload)
        self.assertNotIn('codEstable', payload['emisor'])
        self.assertEqual(payload['receptor']['tipoDocumento'], '36')
        item, resumen = payload['cuerpoDocumento'][0], payload['resumen']
        self.assertEqual(item['numeroDocumento'], origen.l10n_sv_dte_codigo_generacion)
        self.assertIsNone(item['tributos'])
        self.assertAlmostEqual(item['totalIva'], 13.0, places=2)
        self.assertAlmostEqual(resumen['totalIva'], 13.0, places=2)
        self.assertIsNone(resumen['tributos'])
        self.assertAlmostEqual(resumen['subTotalVentas'] + resumen['totalIva'], resumen['montoTotalOperacion'], places=2)
        self.assertAlmostEqual(resumen['totalPagar'], nc.amount_total, places=2)
        self.assertNotIn('pagos', resumen)

    def test_13_nd_matches_schema(self):
        origen = self._create_processed_ccf()
        nd = self._create_nota('06', origen, precio=25.0)
        nd.write({'l10n_sv_dte_num_pago_electronico': 'REF-ND'})
        payload = nd.action_generate_dte_json()
        self.assertEqual(self._errors(payload), [])
        self.assertEqual(payload['identificacion']['tipoDte'], '06')
        self.assertEqual(payload['documentoRelacionado'][0]['numeroDocumento'], origen.l10n_sv_dte_codigo_generacion)
        self.assertEqual(payload['resumen']['numPagoElectronico'], 'REF-ND')
        self.assertTrue(payload['identificacion']['numeroControl'].startswith('DTE-06-M001P001-'))

    def test_14_nota_requires_origin(self):
        for tipo in ('05', '06'):
            with self.assertRaises(UserError) as ctx:
                self._create_nota(tipo, None).action_generate_dte_json()
            self.assertIn('vincularse', str(ctx.exception))

    def test_15_nota_requires_processed_ccf(self):
        sin_procesar = self._create_invoice(tipo_dte='03')
        sin_procesar.action_post()
        sin_procesar.action_generate_dte_json()
        with self.assertRaises(UserError) as ctx:
            self._create_nota('05', sin_procesar).action_generate_dte_json()
        self.assertIn('no fue procesado', str(ctx.exception))
        fcf = self._create_invoice(tipo_dte='01')
        fcf.action_post()
        with self.assertRaises(UserError) as ctx:
            self._create_nota('05', fcf).action_generate_dte_json()
        self.assertIn('CCF', str(ctx.exception))

    def test_16_invalid_nota_payload_raises(self):
        payload = self._create_nota('05', self._create_processed_ccf()).action_generate_dte_json()
        payload['documentoRelacionado'] = []
        payload['resumen']['pagos'] = []
        with self.assertRaises(UserError) as ctx:
            self.env['l10n_sv.dte.schema']._validate(payload)
        self.assertIn('documentoRelacionado', str(ctx.exception))
        self.assertIn('pagos', str(ctx.exception))
