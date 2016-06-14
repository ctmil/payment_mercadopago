# -*- coding: utf-'8' "-*-"

import base64
try:
    import simplejson as json
except ImportError:
    import json
import logging
import urlparse
import werkzeug.urls
import urllib2
from datetime import datetime, timedelta

from openerp import api, fields, models
from openerp.addons.payment.models.payment_acquirer import ValidationError
from openerp.addons.payment_mercadopago.controllers.main \
    import MercadoPagoController
from openerp.addons.payment_mercadopago.mercadopago import \
    mercadopago
from ..mercadopago.mercadopago import MLDATETIME

_logger = logging.getLogger(__name__)


class AcquirerMercadopago(models.Model):
    _inherit = 'payment.acquirer'

    def _get_mercadopago_urls(self, environment):
        """ MercadoPago URLS """
        if environment == 'prod':
            return {
                'mercadopago_form_url':
                'https://www.mercadopago.com/mla/checkout/pay',
                'mercadopago_rest_url':
                'https://api.mercadolibre.com/oauth/token',
            }
        else:
            return {
                'mercadopago_form_url':
                'https://sandbox.mercadopago.com/mla/checkout/pay',
                'mercadopago_rest_url':
                'https://api.sandbox.mercadolibre.com/oauth/token',
            }

    @api.model
    def _get_providers(self):
        providers = super(AcquirerMercadopago, self)._get_providers()
        providers.append(['mercadopago', 'MercadoPago'])
        return providers

    mercadopago_client_id = fields.Char(
        'MercadoPago Client Id',
        required_if_provider='mercadopago')
    mercadopago_secret_key = fields.Char(
        'MercadoPago Secret Key',
        required_if_provider='mercadopago')
    mercadopago_email_account = fields.Char(
        'MercadoPago Email ID',
        required_if_provider='mercadopago')
    mercadopago_seller_account = fields.Char(
        'MercadoPago Merchant ID',
        help='The Merchant ID is used to ensure'
        ' communications coming from MercadoPago'
        ' are valid and secured.')
    mercadopago_use_ipn = fields.Boolean(
        'Use IPN',
        help='MercadoPago Instant Payment Notification',
        default=True
    )

    # Server 2 server
    mercadopago_api_enabled = fields.Boolean(
        'Use Rest API')
    mercadopago_api_username = fields.Char(
        'Rest API Username')
    mercadopago_api_password = fields.Char(
        'Rest API Password')
    mercadopago_api_access_token = fields.Char(
        'Access Token')
    mercadopago_api_access_token_validity = fields.Datetime(
        'Access Token Validity')

    _defaults = {
        'fees_active': False,
        'fees_dom_fixed': 0.35,
        'fees_dom_var': 3.4,
        'fees_int_fixed': 0.35,
        'fees_int_var': 3.9,
        'mercadopago_api_enabled': False,
    }

    @api.multi
    def mercadopago_compute_fees(self, amount, currency_id, country_id):
        """
        Compute mercadopago fees.
        :param float amount: the amount to pay
        :param integer country_id: an ID of a res.country, or None. This is
                                   the customer's country, to be compared to
                                   the acquirer company country.
        :return float fees: computed fees
        """
        self.ensure_one()
        acquirer = self
        if not acquirer.fees_active:
            return 0.0
        country = self.env('res.country').browse(country_id)
        if country and acquirer.company_id.country_id.id == country.id:
            percentage = acquirer.fees_dom_var
            fixed = acquirer.fees_dom_fixed
        else:
            percentage = acquirer.fees_int_var
            fixed = acquirer.fees_int_fixed
        fees = (percentage / 100.0 * amount + fixed) / (1 - percentage / 100.0)
        return fees

    @api.multi
    def mercadopago_form_generate_values(self, values):
        partner_values = values
        tx_values = values
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url')
        acquirer = self

        MPago = False

        if not acquirer.mercadopago_client_id or \
           not acquirer.mercadopago_secret_key:
            error_msg = 'YOU MUST COMPLETE acquirer.mercadopago_client_id'\
                ' and acquirer.mercadopago_secret_key'
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        MPago = mercadopago.MP(acquirer.mercadopago_client_id,
                               acquirer.mercadopago_secret_key)

        if not MPago:
            error_msg = 'Can\'t create mercadopago instance.'
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        if acquirer.environment == "prod":
            MPago.sandbox_mode(False)
        else:
            MPago.sandbox_mode(True)

        MPago.get_access_token()

        date_from = fields.Datetime \
            .context_timestamp(self, datetime.now())

        preference = {
            "items": [{
                "title": "Orden Ecommerce " + tx_values["reference"],
                "quantity": 1,
                "currency_id":  tx_values['currency']
                and tx_values['currency'].name or '',
                "unit_price": tx_values["amount"]
            }],
            "payer": {
                "name": partner_values["billing_partner_first_name"],
                "surname": partner_values["billing_partner_last_name"],
                "email": partner_values["billing_partner_email"]
            },
            "back_urls": {
                "success": '%s' % urlparse.urljoin(
                    base_url, MercadoPagoController._return_url),
                "failure": '%s' % urlparse.urljoin(
                    base_url, MercadoPagoController._cancel_url),
                "pending": '%s' % urlparse.urljoin(
                    base_url, MercadoPagoController._return_url)
            },
            "auto_return": "approved",
            "notification_url": '%s' % urlparse.urljoin(
                base_url, MercadoPagoController._notify_url),
            "external_reference": tx_values["reference"],
            "expires": True,
            "expiration_date_from": date_from.strftime(MLDATETIME),
            "expiration_date_to": (date_from + timedelta(days=2))
            .strftime(MLDATETIME)
        }

        preferenceResult = MPago.create_preference(preference)

        if 'response' in preferenceResult \
                and 'id' in preferenceResult['response']:
            tx_values["pref_id"] = preferenceResult['response']['id']
        else:
            error_msg = 'Returning response is:'
            error_msg += json.dumps(preferenceResult, indent=2)
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        tx_values['tx_url'] = preferenceResult['response']['init_point'] \
            if acquirer.environment == "prod" \
            else preferenceResult['response']['sandbox_init_point']

        return tx_values

    @api.multi
    def mercadopago_get_form_action_url(self):
        acquirer = self
        mercadopago_urls = self._get_mercadopago_urls(
            acquirer.environment)['mercadopago_form_url']
        return mercadopago_urls

    @api.multi
    def _mercadopago_s2s_get_access_token(self):
        """
        Note: see
        http://stackoverflow.com/questions/2407126/python-urllib2-basic-auth-problem
        for explanation why we use Authorization header instead of urllib2
        password manager
        """
        res = dict.fromkeys(self.ids, False)
        parameters = werkzeug.url_encode({'grant_type': 'client_credentials'})

        for acquirer in self:
            tx_url = self._get_mercadopago_urls(
                acquirer.environment)['mercadopago_rest_url']
            request = urllib2.Request(tx_url, parameters)

            request.add_header('Accept', 'application/json')
            request.add_header('Accept-Language', 'en_US')

            base64string = base64.encodestring('%s:%s' % (
                acquirer.mercadopago_api_username,
                acquirer.mercadopago_api_password)
            ).replace('\n', '')
            request.add_header("Authorization", "Basic %s" % base64string)

            request = urllib2.urlopen(request)
            result = request.read()
            res[acquirer.id] = json.loads(result).get('access_token')
            request.close()
        return res


class TxMercadoPago(models.Model):
    _inherit = 'payment.transaction'

    mercadopago_txn_id = fields.Char('Transaction ID')
    mercadopago_txn_type = fields.Char('Transaction type')

    # --------------------------------------------------
    # FORM RELATED METHODS
    # --------------------------------------------------

    @api.multi
    def _mercadopago_form_get_tx_from_data(self, cr, uid, data, context=None):
        reference, collection_id =\
            data.get('external_reference'), data.get('collection_id')
        if not reference or not collection_id:
            error_msg = 'MercadoPago: received data with missing reference'\
                ' (%s) or collection_id (%s)' % (reference, collection_id)
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        tx_ids = self.env['payment.transaction'].search(
            [('reference', '=', reference)])
        if not tx_ids or len(tx_ids) > 1:
            error_msg = 'MercadoPago: received data for reference %s' %\
                (reference)
            if not tx_ids:
                error_msg += '; no order found'
            else:
                error_msg += '; multiple order found'
            _logger.error(error_msg)
            raise ValidationError(error_msg)
        return self.browse(cr, uid, tx_ids[0], context=context)

    @api.multi
    def _mercadopago_form_get_invalid_parameters(self, data):
        invalid_parameters = []
        _logger.warning('Received a notification from MercadoLibre.')

        return invalid_parameters

    @api.multi
    def _mercadopago_form_validate(self, data):
        tx = self
        status = data.get('collection_status')
        data = {
            'acquirer_reference': data.get('external_reference'),
            'mercadopago_txn_type': data.get('payment_type')
        }
        if status in ['approved', 'processed']:
            _logger.info('Validated MercadoPago payment for tx %s: set as done'
                         % (tx.reference))
            data.update(
                state='done',
                date_validate=data.get('payment_date', fields.datetime.now()))
            return tx.write(data)
        elif status in ['pending', 'in_process', 'in_mediation']:
            _logger.info('Received notification for MercadoPago payment %s:'
                         ' set as pending' % (tx.reference))
            data.update(
                state='pending', state_message=data.get('pending_reason', ''))
            return tx.write(data)
        elif status in ['cancelled', 'refunded', 'charged_back', 'rejected']:
            _logger.info('Received notification for MercadoPago payment %s:'
                         ' set as cancelled' % (tx.reference))
            data.update(state='cancel',
                        state_message=data.get('cancel_reason', ''))
            return tx.write(data)
        else:
            error = 'Received unrecognized status for MercadoPago payment %s:'\
                ' %s, set as error' % (tx.reference, status)
            _logger.info(error)
            data.update(state='error', state_message=error)
            return tx.write(data)

    # --------------------------------------------------
    # SERVER2SERVER RELATED METHODS
    # --------------------------------------------------

    @api.model
    def _mercadopago_try_url(self, request, tries=3):
        """ Try to contact MercadoPago. Due to some issues, internal service errors
        seem to be quite frequent. Several tries are done before considering
        the communication as failed.

         .. versionadded:: pre-v8 saas-3
         .. warning::

            Experimental code. You should not use it before OpenERP v8 official
            release.
        """
        done, res = False, None
        while (not done and tries):
            try:
                res = urllib2.urlopen(request)
                done = True
            except urllib2.HTTPError as e:
                res = e.read()
                e.close()
                if tries and res and \
                        json.loads(res)['name'] == 'INTERNAL_SERVICE_ERROR':
                    _logger.warning('Failed contacting MercadoPago,'
                                    ' retrying (%s remaining)' % tries)
            tries = tries - 1
        if not res:
            pass
            # raise openerp.exceptions.
        result = res.read()
        res.close()
        return result

    @api.model
    def _mercadopago_s2s_send(self, values, cc_values):
        """
         .. versionadded:: pre-v8 saas-3
         .. warning::

            Experimental code. You should not use it before OpenERP v8 official
            release.
        """
        tx = self.create(values)

        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer %s' %
            tx.acquirer_id._mercadopago_s2s_get_access_token(
            )[tx.acquirer_id.id],
        }
        data = {
            'intent': 'sale',
            'transactions': [{
                'amount': {
                    'total': '%.2f' % tx.amount,
                    'currency': tx.currency_id.name,
                },
                'description': tx.reference,
            }]
        }
        if cc_values:
            data['payer'] = {
                'payment_method': 'credit_card',
                'funding_instruments': [{
                    'credit_card': {
                        'number': cc_values['number'],
                        'type': cc_values['brand'],
                        'expire_month': cc_values['expiry_mm'],
                        'expire_year': cc_values['expiry_yy'],
                        'cvv2': cc_values['cvc'],
                        'first_name': tx.partner_name,
                        'last_name': tx.partner_name,
                        'billing_address': {
                            'line1': tx.partner_address,
                            'city': tx.partner_city,
                            'country_code': tx.partner_country_id.code,
                            'postal_code': tx.partner_zip,
                        }
                    }
                }]
            }
        else:
            # TODO: complete redirect URLs
            data['redirect_urls'] = {
                # 'return_url': 'http://example.com/your_redirect_url/',
                # 'cancel_url': 'http://example.com/your_cancel_url/',
            },
            data['payer'] = {
                'payment_method': 'mercadopago',
            }
        data = json.dumps(data)

        request = urllib2.Request(
            'https://api.sandbox.paypal.com/v1/payments/payment', data, headers)
        result = self._mercadopago_try_url(request, tries=3)
        return (tx.id, result)

    @api.model
    def _mercadopago_s2s_get_invalid_parameters(self, data):
        """
         .. versionadded:: pre-v8 saas-3
         .. warning::

            Experimental code. You should not use it before OpenERP v8 official
            release.
        """
        invalid_parameters = []
        return invalid_parameters

    @api.multi
    def _mercadopago_s2s_validate(self, data):
        """
         .. versionadded:: pre-v8 saas-3
         .. warning::

            Experimental code. You should not use it before OpenERP v8 official
            release.
        """
        tx = self
        values = json.loads(data)
        status = values.get('state')
        if status in ['approved']:
            _logger.info('Validated Mercadopago s2s payment for tx %s:'
                         ' set as done' % (tx.reference))
            tx.write({
                'state': 'done',
                'date_validate': values.get('udpate_time',
                                            fields.datetime.now()),
                'mercadopago_txn_id': values['id'],
            })
            return True
        elif status in ['pending', 'expired']:
            _logger.info('Received notification for MercadoPago s2s payment %s:'
                         ' set as pending' % (tx.reference))
            tx.write({
                'state': 'pending',
                # 'state_message': data.get('pending_reason', ''),
                'mercadopago_txn_id': values['id'],
            })
            return True
        else:
            error = 'Received unrecognized status for MercadoPago'\
                ' s2s payment %s: %s, set as error' % (tx.reference, status)
            _logger.info(error)
            tx.write({
                'state': 'error',
                # 'state_message': error,
                'mercadopago_txn_id': values['id'],
            })
            return False

    @api.multi
    def _mercadopago_s2s_get_tx_status(self):
        """
         .. versionadded:: pre-v8 saas-3
         .. warning::

            Experimental code. You should not use it before OpenERP v8 official
            release.
        """
        # TDETODO: check tx.mercadopago_txn_id is set
        tx = self
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer %s' %
            tx.acquirer_id._mercadopago_s2s_get_access_token(
            )[tx.acquirer_id.id],
        }
        url = 'https://api.sandbox.paypal.com/v1/payments/payment/%s' %\
            (tx.mercadopago_txn_id)
        request = urllib2.Request(url, headers=headers)
        data = self._mercadopago_try_url(request, tries=3)
        return tx.s2s_feedback(data)
