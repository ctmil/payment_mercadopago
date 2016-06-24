# -*- coding: utf-'8' "-*-"

try:
    import simplejson as json
except ImportError:
    import json
import logging
import urlparse
import urllib2
from datetime import datetime, timedelta

from openerp import api, fields, models
from openerp.exceptions import ValidationError
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
        print "[%s]mercadopago_compute_fees" % __name__
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
        print "[%s]mercadopago_form_generate_values" % __name__
        self.ensure_one()

        acquirer = self

        if not acquirer.mercadopago_client_id or \
           not acquirer.mercadopago_secret_key:
            error_msg = 'YOU MUST COMPLETE acquirer.mercadopago_client_id'\
                ' and acquirer.mercadopago_secret_key'
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        if values.get("reference", "/") != "/":
            values["acquirer_reference"], values['tx_url'] = acquirer \
                .mercadopago_create_preference(values)

        return values

    @api.multi
    def mercadopago_create_preference(self, values):
        """
        Create a MercadoPago preference and related pending transaction.
        """
        self.ensure_one()
        acquirer = self

        # Setup MercadoPago.
        MPago = mercadopago.MP(acquirer.mercadopago_client_id,
                               acquirer.mercadopago_secret_key)

        if not MPago:
            error_msg = 'Can\'t create mercadopago instance.'
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        MPago.sandbox_mode(acquirer.environment != "prod")

        # Requiered data to setup preferences.
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url')
        date_from = fields.Datetime \
            .context_timestamp(self, datetime.now())

        # Setup Preference.
        preference = {
            "items": [{
                "title": "Orden Ecommerce " + values["reference"],
                "quantity": 1,
                "currency_id":  values['currency']
                and values['currency'].name or '',
                "unit_price": values["amount"]
            }],
            "payer": {
                "name": values["billing_partner_first_name"],
                "surname": values["billing_partner_last_name"],
                "email": values["billing_partner_email"]
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
            "external_reference": values["reference"],
            "expires": True,
            "expiration_date_from": date_from.strftime(MLDATETIME),
            "expiration_date_to": (date_from + timedelta(days=2))
            .strftime(MLDATETIME)
        }

        # Generate Preference.
        res = MPago.create_preference(preference)

        print "Pref:", res

        if 'response' not in res or 'id' not in res['response']:
            error_msg = 'Returning response is:'
            error_msg += json.dumps(res, indent=2)
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        pref_id = res['response']['id']
        form_url = res['response']['init_point'] \
            if acquirer.environment == "prod" \
            else res['response']['sandbox_init_point']

        return pref_id, form_url

    @api.multi
    def mercadopago_get_form_action_url(self):
        print "[%s]mercadopago_get_form_action_url" % __name__
        acquirer = self
        mercadopago_urls = self._get_mercadopago_urls(
            acquirer.environment)['mercadopago_form_url']
        return mercadopago_urls

    @api.multi
    def _mercadopago_s2s_get_access_token(self):
        """
        """
        print "[%s]_mercadopago_s2s_get_access_token" % __name__

        res = dict.fromkeys(self.ids, False)
        for acquirer in self:
            MPago = mercadopago.MP(acquirer.mercadopago_client_id,
                                   acquirer.mercadopago_secret_key)
            res[acquirer.id] = MPago.get_access_token()
        return res

    @api.model
    def mercadopago_get_merchant_order(self, merchant_order_id):
        print "[%s]mercadopago_get_merchant_order" % __name__
        self.ensure_one()
        acq = self
        MPago = mercadopago.MP(acq.mercadopago_client_id,
                               acq.mercadopago_secret_key)
        merchant_order = MPago.get_merchant_order(merchant_order_id)

        return merchant_order.get('response', False)

    @api.model
    def mercadopago_get_transaction_by_merchant_order(self, merchant_order_id):
        print "[%s]mercadopago_get_transaction_by_merchant_order" % __name__
        transaction = self.env['payment.transaction']

        res = transaction
        mos = []
        for acq in self.search([('provider', '=', 'mercadopago')]):
            merchant_order = acq \
                .mercadopago_get_merchant_order(merchant_order_id)

            external_reference = merchant_order.get('external_reference')
            if not external_reference:
                continue

            txs = transaction.search(
                [('reference', '=', external_reference),
                 ('acquirer_id', '=', acq.id)],
                )
            txs._merchant_order_ = merchant_order

            res = res | txs
            mos.append(merchant_order)

        return res, mos

    @api.model
    def mercadopago_get_collection(self, collection_id):
        print "[%s]mercadopago_get_collection" % __name__

        self.ensure_one()
        acq = self
        MPago = mercadopago.MP(acq.mercadopago_client_id,
                               acq.mercadopago_secret_key)
        collection_info = MPago.get_collection(collection_id)

        return collection_info.get('response', {}).get('collection', False)

    @api.model
    def mercadopago_get_transaction_by_collection(self, collection_id):
        print "[%s]mercadopago_get_transaction_by_collection" % __name__

        transaction = self.env['payment.transaction']

        res = transaction
        cos = []
        for acq in self.search([('provider', '=', 'mercadopago')]):
            collection = acq \
                .mercadopago_get_collection(collection_id)

            external_reference = collection.get('external_reference')

            if not external_reference:
                continue

            txs = transaction.search(
                [('reference', '=', external_reference),
                 ('acquirer_id', '=', acq.id)],
                )
            txs._collection_ = collection

            res = res | txs
            cos.append(collection)

        return res, cos


class TxMercadoPago(models.Model):
    _inherit = 'payment.transaction'

    @api.model
    def _mercadopago_form_get_tx_from_data(self, data):
        print "[%s]_mercadopago_form_get_tx_from_data" % __name__
        reference = data.get('external_reference')

        if not reference:
            error_msg = 'MercadoPago: received data with missing reference'\
                ' (%s)' % (reference)
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        tx = self.search([('reference', '=', reference)])
        if not tx or len(tx) > 1:
            error_msg = 'MercadoPago: received data for reference %s' %\
                (reference)
            if not tx:
                error_msg += '; no order found'
            else:
                error_msg += '; multiple order found'
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        return tx[0]

    @api.model
    def _mercadopago_form_get_invalid_parameters(self, tx, data):
        print "[%s]_mercadopago_form_get_invalid_parameters" % __name__
        return []

    @api.model
    def _mercadopago_form_validate(self, tx, data):
        print "[%s]_mercadopago_form_validate" % __name__
        status = data.get('collection_status') or data.get('status_detail')
        pay = tx.env['payment.method']
        data = {
            'acquirer_reference': data.get('merchant_order_id'),
            'payment_method_id': (
                pay.search([('acquirer_ref', '=', data.get('payment_type'))])
                or
                pay.create({
                    'name': data.get('payment_type'),
                    'acquirer_ref': data.get('payment_type'),
                    'partner_id':  tx.acquirer_id.company_id.partner_id.id,
                    'acquirer_id': tx.acquirer_id.id})
            ).id
        }
        if status in ['approved', 'processed', 'accredited']:
            _logger.info('Validated MercadoPago payment for tx %s: set as done'
                         % (tx.reference))
            data.update(
                state='done',
                date_validate=data.get('payment_date', fields.datetime.now())
            )
        elif status in ['pending', 'in_process', 'in_mediation']:
            _logger.info('Received notification for MercadoPago payment %s:'
                         ' set as pending' % (tx.reference))
            data.update(
                state='pending',
                state_message=data.get('pending_reason', '')
            )
        elif status in ['cancelled', 'refunded', 'charged_back', 'rejected']:
            _logger.info('Received notification for MercadoPago payment %s:'
                         ' set as cancelled' % (tx.reference))
            data.update(
                state='cancel',
                state_message=data.get('cancel_reason', '')
            )
        else:
            error = 'Received unrecognized status for MercadoPago payment %s:'\
                ' %s, set as error' % (tx.reference, status)
            _logger.info(error)
            data.update(
                state='error',
                state_message=error)
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
        print "[%s]_mercadopago_try_url" % __name__
        raise NotImplemented
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
        print "[%s]_mercadopago_s2s_send" % __name__
        raise NotImplemented

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
        print "[%s]_mercadopago_s2s_get_invalid_parameters" % __name__
        raise NotImplemented
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
        print "[%s]_mercadopago_s2s_validate" % __name__
        raise NotImplemented
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
        print "[%s]_mercadopago_s2s_get_tx_status" % __name__
        raise NotImplemented
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
