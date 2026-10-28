import base64
import json

from odoo.tests import tagged
from odoo.exceptions import UserError

from .common import L10nSvDteTestBase, build_mh_style_cert_xml


@tagged('post_install', '-at_install', 'l10n_sv_dte', 'l10n_sv_dte_signer')
class TestL10nSvSigner(L10nSvDteTestBase):

    def test_01_parse_mh_certificate_returns_rsa_key(self):
        signer = self.env['l10n_sv.signer'].sudo()
        key = signer.parse_mh_certificate(self.cert_xml)
        self.assertIsNotNone(key)
        self.assertEqual(key.key_size, 2048)

    def test_02_parse_mh_certificate_rejects_non_xml(self):
        signer = self.env['l10n_sv.signer'].sudo()
        with self.assertRaises(Exception):
            signer.parse_mh_certificate(b'this is not xml')

    def test_03_parse_mh_certificate_rejects_missing_key(self):
        signer = self.env['l10n_sv.signer'].sudo()
        bad_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<dte:certificado xmlns:dte="http://www.mh.gob.sv/dte">'
            '<dte:datosEmisor><dte:nit>123</dte:nit></dte:datosEmisor>'
            '</dte:certificado>'
        ).encode('utf-8')
        with self.assertRaises(UserError):
            signer.parse_mh_certificate(bad_xml)

    def test_04_sign_dte_produces_jws_compact_format(self):
        signer = self.env['l10n_sv.signer'].sudo()
        payload = {'foo': 'bar', 'numero': 1}
        jws = signer.sign_dte(payload, self.key, TEST_NIT_DIGITS := '06141406100012')
        parts = jws.split('.')
        self.assertEqual(len(parts), 3, 'JWS compact format requires 3 parts')
        header_b64, payload_b64, signature_b64 = parts
        header = json.loads(self._b64url_decode(header_b64))
        self.assertEqual(header.get('alg'), 'RS512')
        self.assertEqual(header.get('kid'), TEST_NIT_DIGITS)
        decoded = json.loads(self._b64url_decode(payload_b64))
        self.assertEqual(decoded, payload)
        self.assertGreater(len(signature_b64), 100)

    def test_05_signature_is_verifiable_with_public_key(self):
        signer = self.env['l10n_sv.signer'].sudo()
        payload = {'identificacion': {'tipoDte': '01'}, 'monto': 116.0}
        jws = signer.sign_dte(payload, self.key, '06141406100012')
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
        header_b64, payload_b64, signature_b64 = jws.split('.')
        signing_input = (header_b64 + '.' + payload_b64).encode('ascii')
        signature = self._b64url_decode_bytes(signature_b64)
        self.key.public_key().verify(
            signature, signing_input, asym_padding.PKCS1v15(), hashes.SHA512(),
        )

    def test_06_tampered_payload_fails_verification(self):
        signer = self.env['l10n_sv.signer'].sudo()
        payload = {'monto': 100}
        jws = signer.sign_dte(payload, self.key, '06141406100012')
        header_b64, _, signature_b64 = jws.split('.')
        tampered_payload = self._b64url_encode_bytes(
            json.dumps({'monto': 9999}, separators=(',', ':')).encode('utf-8'),
        )
        tampered = (header_b64 + '.' + tampered_payload + '.' + signature_b64)
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
        from cryptography.exceptions import InvalidSignature
        signing_input = (header_b64 + '.' + tampered_payload).encode('ascii')
        signature = self._b64url_decode_bytes(signature_b64)
        with self.assertRaises(InvalidSignature):
            self.key.public_key().verify(
                signature, signing_input, asym_padding.PKCS1v15(), hashes.SHA512(),
            )

    def test_07_sign_and_store_uses_company_cert(self):
        signer = self.env['l10n_sv.signer'].sudo()
        invoice = self._create_invoice()
        jws = signer._sign_and_store(invoice, {'fake': 'payload'})
        self.assertEqual(len(jws.split('.')), 3)

    def _b64url_decode(self, s):
        pad = '=' * (-len(s) % 4)
        return base64.urlsafe_b64decode(s + pad).decode('utf-8')

    def _b64url_decode_bytes(self, s):
        pad = '=' * (-len(s) % 4)
        return base64.urlsafe_b64decode(s + pad)

    def _b64url_encode_bytes(self, b):
        return base64.urlsafe_b64encode(b).rstrip(b'=').decode('ascii')
