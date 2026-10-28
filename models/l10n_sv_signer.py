"""
Firmador JWS para DTE del Ministerio de Hacienda de El Salvador.

Soporta firma con algoritmo RS512 (RSASSA-PKCS1-v1_5 con SHA-512) tal como
lo requiere el MH. El certificado es el archivo XML emitido por el MH
que contiene la clave privada RSA en Base64.

Para usar este módulo, agregue la dependencia externa:
    pip install cryptography
"""

import base64
import hashlib
import json
import logging

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

JWS_ALGORITHM = 'RS512'


def _b64url_encode(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64url_decode(s):
    padding_needed = 4 - (len(s) % 4)
    if padding_needed != 4:
        s = s + ('=' * padding_needed)
    return base64.urlsafe_b64decode(s)


class L10nSvSigner(models.AbstractModel):
    _name = 'l10n_sv.signer'
    _description = 'Firmador JWS para DTE Ministerio de Hacienda SV'

    @staticmethod
    def parse_mh_certificate(cert_xml_bytes):
        """
        Extrae la clave privada RSA del certificado XML emitido por el MH.

        Formato esperado (simplificado):
        <?xml version="1.0" encoding="UTF-8"?>
        <certificate>
            <privateKey>
                <encodied>BASE64_PEM_RSA_PRIVATE_KEY</encodied>
            </privateKey>
            <publicKey>...</publicKey>
        </certificate>

        :param cert_xml_bytes: Contenido binario del XML del certificado
        :return: cryptography.hazmat.primitives.serialization.RSAPrivateKey
        """
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(cert_xml_bytes)
        except ET.ParseError as e:
            raise UserError(_('El archivo del certificado no es un XML válido: %s') % e)

        embodied = None
        for elem in root.iter():
            if elem.tag.lower().endswith('encodied') and elem.text:
                parent_tag = ''
                for p in root.iter():
                    if elem in list(p):
                        parent_tag = p.tag.lower()
                        break
                if 'private' in parent_tag:
                    embodied = elem.text
                    break

        if not embodied:
            for elem in root.iter():
                if elem.tag.lower().endswith('encodied') and elem.text:
                    embodied = elem.text
                    break

        if not embodied:
            raise UserError(_('No se encontró el elemento <encodied> con la clave privada dentro de <privateKey> en el certificado.'))

        try:
            pem_bytes = base64.b64decode(embodied)
        except Exception as e:
            raise UserError(_('El contenido del certificado no es Base64 válido: %s') % e)

        try:
            private_key = serialization.load_pem_private_key(
                pem_bytes, password=None, backend=default_backend(),
            )
        except Exception as e:
            raise UserError(_('No se pudo cargar la clave privada PEM del certificado: %s') % e)

        return private_key

    @staticmethod
    def _b64url_to_bytes(payload):
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        return payload

    def sign_dte(self, dte_payload, private_key, nit_emisor):
        """
        Firma el payload del DTE como un JWS en formato compacto (RS512).

        Estructura del JWS:
          base64url(header) . base64url(payload) . base64url(signature)

        Header: {"alg": "RS512", "kid": "<NIT>"}
        Payload: JSON serializado del DTE (sin transformación, bytes UTF-8)

        :param dte_payload: dict con la estructura del DTE
        :param private_key: RSAPrivateKey cargada con parse_mh_certificate
        :param nit_emisor: NIT del emisor (usado como kid en el header)
        :return: str JWS en formato compacto (3 segmentos separados por '.')
        """
        header = {'alg': JWS_ALGORITHM, 'kid': nit_emisor}
        header_b64 = _b64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
        payload_b64 = _b64url_encode(json.dumps(dte_payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))

        signing_input = (header_b64 + '.' + payload_b64).encode('ascii')
        try:
            signature = private_key.sign(
                signing_input,
                padding.PKCS1v15(),
                hashes.SHA512(),
            )
        except Exception as e:
            raise UserError(_('Error al firmar el DTE con la clave privada: %s') % e)

        signature_b64 = _b64url_encode(signature)
        jws = '%s.%s.%s' % (header_b64, payload_b64, signature_b64)

        _logger.info('JWS firmado correctamente (kid=%s, alg=%s)', nit_emisor, JWS_ALGORITHM)
        return jws

    def _load_company_private_key(self, company):
        cert_b64 = company.sudo().l10n_sv_certificate
        if not cert_b64:
            raise UserError(_('La compañía no tiene un certificado digital MH configurado. Suba el archivo .crt en la configuración de la compañía.'))
        try:
            cert_bytes = base64.b64decode(cert_b64)
        except Exception:
            raise UserError(_('El archivo del certificado está vacío o no se pudo leer.'))
        return self.parse_mh_certificate(cert_bytes)

    def _sign_and_store(self, move, dte_payload):
        """
        Carga la clave privada del certificado adjunto a la compañía,
        firma el DTE y almacena el JWS en el account.move.

        :param move: account.move record
        :param dte_payload: dict con la estructura del DTE
        :return: str JWS firmado
        """
        company = move.company_id
        private_key = self._load_company_private_key(company)
        nit = company.l10n_sv_nit_emisor or company.l10n_sv_nit or ''
        if not nit:
            raise UserError(_('La compañía no tiene configurado un NIT para la firma (campo l10n_sv_nit_emisor o l10n_sv_nit).'))

        jws = self.sign_dte(dte_payload, private_key, nit)
        return jws
