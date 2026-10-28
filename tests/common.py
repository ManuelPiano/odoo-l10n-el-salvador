"""
Helpers compartidos por los tests de l10n_sv_dte.

Genera un certificado de prueba (par de claves RSA 2048 + certificado
auto-firmado) envuelto en un XML que imita el formato que entrega el MH
de El Salvador: <privateKey><encodied>BASE64_PEM</encodied></privateKey>.
"""
import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography import x509
from cryptography.x509.oid import NameOID
import datetime

from odoo.tests import TransactionCase


TEST_NIT = '06141406100012'
TEST_NIT_DIGITS = TEST_NIT.replace('-', '').replace(' ', '')
TEST_NRC = '1234567'
TEST_COD_ESTABLE = 'M001'
TEST_COD_PUNTO_VENTA = 'P001'


def generate_test_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return key, pem


def build_mh_style_cert_xml(private_pem: bytes) -> bytes:
    b64 = base64.b64encode(private_pem).decode('ascii')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<dte:certificado xmlns:dte="http://www.mh.gob.sv/dte">'
        '<dte:datosEmisor>'
        '<dte:nit>%s</dte:nit>'
        '</dte:datosEmisor>'
        '<dte:privateKey>'
        '<dte:encodied>%s</dte:encodied>'
        '</dte:privateKey>'
        '</dte:certificado>'
    ) % (TEST_NIT_DIGITS, b64)


class L10nSvDteTestBase(TransactionCase):
    """
    SetUp común: crea una compañía, partner, certificados y cargas datos
    mínimos necesarios para que los builders de JSON DTE funcionen.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key, cls.pem = generate_test_keypair()
        cls.cert_xml = build_mh_style_cert_xml(cls.pem)

        cls.company = cls.env['res.company'].create({
            'name': 'DIAL Studio Test, S.A. de C.V.',
            'country_id': cls.env.ref('base.sv').id,
            'l10n_sv_nit': TEST_NIT_DIGITS,
            'l10n_sv_nrc': TEST_NRC,
            'l10n_sv_nombre_comercial': 'DIAL Test',
            'l10n_sv_giro': 'Servicios de tecnología',
            'l10n_sv_telefono': '22334455',
            'l10n_sv_correo': 'test@example.com',
            'l10n_sv_cod_estable_mh': TEST_COD_ESTABLE,
            'l10n_sv_cod_punto_venta_mh': TEST_COD_PUNTO_VENTA,
            'l10n_sv_ambiente': '00',
            'l10n_sv_nit_emisor': TEST_NIT_DIGITS,
        })
        cls.company.write({
            'state_id': cls.env['res.country.state'].search(
                [('country_id', '=', cls.env.ref('base.sv').id), ('code', '=', '06')],
                limit=1,
            ).id,
            'street': 'Av. Test 123',
            'account_fiscal_country_id': cls.env.ref('base.sv').id,
        })
        cls.env['account.chart.template'].try_loading('generic_coa', cls.company, install_demo=False)
        cls.company.account_fiscal_country_id = cls.env.ref('base.sv')
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id]))
        cls.company = cls.company.with_env(cls.env)
        cls.municipio = cls.env['l10n_sv.municipio'].search([], limit=1)
        cls.municipio.write({'municipio_mh': '13', 'distrito_mh': '01'})
        cls.actividad = cls.env['l10n_sv.actividad_economica'].search([], limit=1)
        cls.company.write({'l10n_sv_municipio_id': cls.municipio.id})
        cat019 = cls.env['l10n_sv.actividad_economica'].search([], limit=1)
        if cat019:
            cls.company.write({'l10n_sv_cod_actividad_id': cat019.id})
        tipo_estab = cls.env['l10n_sv.tipo_establecimiento'].search([('code', '=', '01')], limit=1)
        if tipo_estab:
            cls.company.write({'l10n_sv_tipo_establecimiento_id': tipo_estab.id})

        cls.company.write({
            'l10n_sv_certificate': base64.b64encode(cls.cert_xml.encode('utf-8')),
            'l10n_sv_certificate_filename': 'test_cert.crt',
        })

        cls.partner = cls.env['res.partner'].create({
            'name': 'Cliente Test, S.A. de C.V.',
            'country_id': cls.env.ref('base.sv').id,
            'l10n_sv_nit': '06140101234567',
            'l10n_sv_nrc': '7654321',
            'l10n_sv_nombre_comercial': 'Cliente Test',
            'l10n_sv_giro': 'Comercio',
            'l10n_sv_cod_actividad_id': cls.actividad.id,
            'phone': '22998877',
            'email': 'cliente@example.com',
            'street': 'Calle Cliente 456',
            'state_id': cls.company.state_id.id,
            'l10n_sv_municipio_id': cls.municipio.id,
        })

        cls.forma_pago = cls.env['l10n_sv.forma_pago'].search([('code', '=', '01')], limit=1)
        cls.condicion_contado = cls.env['l10n_sv.condicion_operacion'].search(
            [('code', '=', '1')], limit=1,
        )

        cls.iva_13 = cls.env['account.tax'].create({
            'name': 'IVA 13% Test',
            'amount': 13.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'company_id': cls.company.id,
            'tax_group_id': cls.env['account.tax.group'].create({
                'name': 'IVA Test', 'company_id': cls.company.id, 'country_id': cls.env.ref('base.sv').id,
            }).id,
            'country_id': cls.env.ref('base.sv').id,
            'l10n_sv_tributo_id': cls.env['l10n_sv.tributo'].search([('code', '=', '20')], limit=1).id,
        })

    def _create_invoice(self, tipo_dte='01', cantidad=1, precio=100.0, descuento=0.0,
                        condicion='1', with_iva=True, partner=None):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'company_id': self.company.id,
            'partner_id': (partner or self.partner).id,
            'invoice_date': '2025-01-15',
            'currency_id': self.env.ref('base.USD').id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Servicio de consultoría',
                'quantity': cantidad,
                'price_unit': precio,
                'discount': descuento,
                'tax_ids': [(6, 0, [self.iva_13.id])] if (with_iva and self.iva_13) else [],
            })],
        })
        invoice.write({
            'l10n_sv_dte_tipo_doc': tipo_dte,
            'l10n_sv_dte_condicion_operacion': condicion,
            'l10n_sv_dte_forma_pago_id': self.forma_pago.id,
        })
        return invoice

    def _create_processed_ccf(self, precio=100.0):
        invoice = self._create_invoice(tipo_dte='03', precio=precio)
        invoice.action_post()
        invoice.action_generate_dte_json()
        invoice._l10n_sv_write({'l10n_sv_dte_state': 'processed', 'l10n_sv_dte_sello_recepcion': 'S' * 40})
        return invoice

    def _create_nota(self, tipo_dte, origen, precio=40.0, cantidad=1):
        vals = {
            'move_type': 'out_refund' if tipo_dte == '05' else 'out_invoice',
            'company_id': self.company.id,
            'partner_id': self.partner.id,
            'invoice_date': '2025-01-20',
            'currency_id': self.env.ref('base.USD').id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Ajuste',
                'quantity': cantidad,
                'price_unit': precio,
                'tax_ids': [(6, 0, [self.iva_13.id])],
            })],
        }
        vals['reversed_entry_id' if tipo_dte == '05' else 'debit_origin_id'] = origen.id if origen else False
        nota = self.env['account.move'].create(vals)
        nota.write({'l10n_sv_dte_tipo_doc': tipo_dte})
        return nota
