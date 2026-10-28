"""
Conector API del Ministerio de Hacienda de El Salvador.

Endpoints soportados:
  - POST /seguridad/auth         (autenticación con user/pwd en form-urlencoded)
  - POST /seguridad/receptordte  (transmisión de DTE firmado)
  - POST /seguridad/anulardte    (invalidación de DTE)
  - POST /seguridad/contingencia (declaración de contingencia)

Maneja cache de token JWT en ir.config_parameter (TTL 1h, refresh con 5min
de margen) y selección automática de URL según ambiente (00=test, 01=prod).
"""

import logging
import time

import requests

from odoo import models, api, _
from odoo.exceptions import AccessError, UserError

from .account_move import CONTINGENCIA_VERSION, DTE_VERSION_MAP, INVALIDACION_VERSION

_logger = logging.getLogger(__name__)

ENDPOINTS = {
    'auth': '/seguridad/auth',
    'receptordte': '/seguridad/receptordte',
    'anulardte': '/seguridad/anulardte',
    'contingencia': '/seguridad/contingencia',
}


DEFAULT_TIMEOUT = 60
TOKEN_TTL_SECONDS = 55 * 60


class L10nSvApi(models.AbstractModel):
    _name = 'l10n_sv.api'
    _description = 'Conector API Ministerio de Hacienda SV'

    @api.model
    def _get_config(self, company=None):
        company = company or self.env.company
        return company._get_l10n_sv_api_config()

    def _get_base_url(self, ambiente):
        if ambiente == '01':
            return 'https://api.dtes.mh.gob.sv'
        return 'https://apitest.dtes.mh.gob.sv'

    def _param_name(self, company_id, suffix):
        return 'l10n_sv.%s_%s' % (suffix, company_id)

    def _cache_get_token(self, company):
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param(self._param_name(company.id, 'token'), default='')
        expires_at = ICP.get_param(self._param_name(company.id, 'token_expires_at'), default='0')
        if not token or not expires_at:
            return None
        try:
            if int(expires_at) < int(time.time()) + 300:
                return None
        except ValueError:
            return None
        return token

    def _cache_set_token(self, company, token, ttl=TOKEN_TTL_SECONDS):
        ICP = self.env['ir.config_parameter'].sudo()
        expires_at = str(int(time.time()) + ttl)
        ICP.set_param(self._param_name(company.id, 'token'), token)
        ICP.set_param(self._param_name(company.id, 'token_expires_at'), expires_at)

    def _cache_clear_token(self, company):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(self._param_name(company.id, 'token'), '')
        ICP.set_param(self._param_name(company.id, 'token_expires_at'), '0')

    @api.model
    def _authenticate(self, company=None, force_refresh=False):
        """
        Obtiene (y cachea) un token JWT del MH.

        :param company: res.company (opcional, default = self.env.company)
        :param force_refresh: bool, si True ignora cache
        :return: str token o None
        """
        company = company or self.env.company
        config = self._get_config(company)
        if not config['api_user'] or not config['api_password']:
            _logger.warning('MH: faltan credenciales API (l10n_sv.api_user / l10n_sv.api_password).')
            return None

        if not force_refresh:
            cached = self._cache_get_token(company)
            if cached:
                return cached

        url = self._get_base_url(config['ambiente']) + ENDPOINTS['auth']
        try:
            _logger.info('MH auth: POST %s (ambiente=%s, user=%r)', ENDPOINTS['auth'], config['ambiente'], config['api_user'])
            response = requests.post(
                url,
                data={'user': config['api_user'], 'pwd': config['api_password']},
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as e:
            _logger.error('Error de red al autenticar con MH: %s', e)
            return None

        if response.status_code != 200:
            _logger.error('Error auth MH %s: %s', response.status_code, response.text)
            return None

        try:
            data = response.json()
        except ValueError:
            _logger.error('Respuesta auth MH no es JSON: %s', response.text[:500])
            return None

        token = (data.get('body') or {}).get('token') or data.get('token')
        if not token:
            _logger.error('Auth MH OK pero sin token. status=%s body=%s', data.get('status'), data.get('body'))
            return None

        self._cache_set_token(company, token)
        _logger.info('Token MH obtenido y cacheado correctamente.')
        return token

    def _post_signed(self, endpoint_key, signed_jws, body_extra=None, company=None, ambiente=None):
        company = company or self.env.company
        config = self._get_config(company)
        ambiente = ambiente or config['ambiente']
        token = self._authenticate(company=company)
        if not token:
            raise UserError(_('No se pudo obtener un token válido del Ministerio de Hacienda. Verifique credenciales en Parámetros del sistema.'))

        url = self._get_base_url(ambiente) + ENDPOINTS[endpoint_key]
        body = {'ambiente': ambiente}
        if body_extra:
            body.update(body_extra)
        body['documento'] = signed_jws

        try:
            response = requests.post(
                url, json=body,
                headers={'Authorization': token, 'Content-Type': 'application/json'},
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as e:
            raise UserError(_('Error de red al comunicarse con MH (%s): %s') % (endpoint_key, e))

        try:
            payload = response.json()
        except ValueError:
            raise UserError(_('Respuesta MH no es JSON. status=%s body=%s') % (response.status_code, response.text[:500]))

        if response.status_code >= 400 or (isinstance(payload, dict) and payload.get('status') == 'ERROR'):
            _logger.error('MH %s error %s: %s', endpoint_key, response.status_code, payload)
            self._cache_clear_token(company)
            return payload

        return payload

    @api.model
    def _get_dte_version(self, tipo_dte):
        return DTE_VERSION_MAP.get(tipo_dte, 1)

    @api.model
    def _send_dte(self, signed_jws, tipo_dte, id_envio=1, ambiente=None, company=None):
        company = company or self.env.company
        config = self._get_config(company)
        ambiente = ambiente or config['ambiente']

        body_extra = {
            'idEnvio': id_envio,
            'version': self._get_dte_version(tipo_dte),
            'tipoDte': tipo_dte,
        }
        result = self._post_signed('receptordte', signed_jws, body_extra=body_extra, company=company, ambiente=ambiente)
        return result

    @api.model
    def _invalidate_dte(self, signed_jws, id_envio=1, ambiente=None, company=None):
        company = company or self.env.company
        config = self._get_config(company)
        ambiente = ambiente or config['ambiente']

        body_extra = {
            'idEnvio': id_envio,
            'version': INVALIDACION_VERSION,
        }
        result = self._post_signed('anulardte', signed_jws, body_extra=body_extra, company=company, ambiente=ambiente)
        return result

    @api.model
    def _send_contingencia(self, signed_jws, id_envio=1, ambiente=None, company=None):
        company = company or self.env.company
        config = self._get_config(company)
        ambiente = ambiente or config['ambiente']

        body_extra = {
            'idEnvio': id_envio,
            'version': CONTINGENCIA_VERSION,
        }
        result = self._post_signed('contingencia', signed_jws, body_extra=body_extra, company=company, ambiente=ambiente)
        return result

    @api.model
    def _test_connection(self, company=None):
        company = company or self.env.company
        return self._authenticate(company=company, force_refresh=True)

    @api.model
    def cron_process_contingencia(self):
        """
        Cron: reintenta enviar al MH todos los DTEs marcados en contingencia.
        Corre cada 5 minutos (configurable en ir.cron).
        Si el servicio del MH responde OK, el DTE pasa a 'processed'.
        Si falla de nuevo, se incrementa el contador de intentos y se registra
        el error en l10n_sv.dte.log; el DTE se mantiene en 'contingencia'
        hasta agotar el máximo de 5 intentos.
        """
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Solo el sistema puede ejecutar el reenvío de contingencia.'))
        Move = self.env['account.move']
        contingent = Move.search([
            ('l10n_sv_dte_state', '=', 'contingencia'),
            ('l10n_sv_dte_contingencia', '=', True),
            ('l10n_sv_dte_send_attempts', '<', 5),
        ])
        _logger.info('DTE contingencia cron: %d DTE(s) pendientes de reenvío.', len(contingent))
        for move in contingent:
            move = move.with_company(move.company_id)
            try:
                move._l10n_sv_write({'l10n_sv_dte_contingencia': False})
                move.action_send_dte(is_automatic=True)
            except Exception as e:
                _logger.warning('Contingencia reenvío falló para %s: %s', move.name, e)
                move._l10n_sv_write({
                    'l10n_sv_dte_contingencia': True,
                    'l10n_sv_dte_state': 'contingencia',
                    'l10n_sv_dte_last_error': str(e),
                })
        return True
