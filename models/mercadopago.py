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

from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.addons.payment_mercadopago.controllers.main import MercadoPagoController
from odoo import osv, fields, models, api
from odoo.tools.float_utils import float_compare
from odoo import SUPERUSER_ID

_logger = logging.getLogger(__name__)


from odoo.addons.payment_mercadopago.mercadopago import mercadopago

class AcquirerMercadopago(models.Model):
    _inherit = 'payment.acquirer'

    def _get_mercadopago_urls(self, environment, context=None):
        """ MercadoPago URLS """
        if environment == 'prod':
            return {
                #https://www.mercadopago.com/mla/checkout/pay?pref_id=153438434-6eb25e49-1bb8-4553-95b2-36033be216ad
                #'mercadopago_form_url': 'https://www.paypal.com/cgi-bin/webscr',
                'mercadopago_form_url': 'https://www.mercadopago.com/mla/checkout/pay',
                'mercadopago_rest_url': 'https://api.mercadolibre.com/oauth/token',
            }
        else:
            return {
                #'mercadopago_form_url': 'https://www.sandbox.paypal.com/cgi-bin/webscr',
                #https://api.mercadolibre.com/oauth/token
                'mercadopago_form_url': 'https://sandbox.mercadopago.com/mla/checkout/pay',
                'mercadopago_rest_url': 'https://api.sandbox.mercadolibre.com/oauth/token',
            }

    def _get_providers(self, context=None):

        providers = super(AcquirerMercadopago, self)._get_providers(cr, uid, context=context)
        providers.append(['mercadopago', 'MercadoPago'])

        print "_get_providers: ", providers

        return providers

    provider = fields.Selection(selection_add=[('mercadopago', 'MercadoPago')])
    #mercadopago_client_id = fields.Char('MercadoPago Client Id',required_if_provider='mercadopago')
    mercadopago_client_id = fields.Char('MercadoPago Client Id', 256)
    #mercadopago_secret_key = fields.Char('MercadoPago Secret Key',required_if_provider='mercadopago')
    mercadopago_secret_key = fields.Char('MercadoPago Secret Key', 256)

    #mercadopago_email_account = fields.Char('MercadoPago Email ID', required_if_provider='mercadopago')
    mercadopago_email_account = fields.Char('MercadoPago Email ID', 256)

    mercadopago_seller_account = fields.Char(
            'MercadoPago Merchant ID',
            help='The Merchant ID is used to ensure communications coming from MercadoPago are valid and secured.')

    mercadopago_use_ipn = fields.Boolean('Use IPN', help='MercadoPago Instant Payment Notification')

    # Server 2 server
    mercadopago_api_enabled = fields.Boolean('Use Rest API')
    mercadopago_api_username = fields.Char('Rest API Username')
    mercadopago_api_password = fields.Char('Rest API Password')
    mercadopago_api_access_token = fields.Char('Access Token')
    mercadopago_api_access_token_validity = fields.Datetime('Access Token Validity')


    _defaults = {
        'mercadopago_use_ipn': True,
        'fees_active': False,
        'fees_dom_fixed': 0.35,
        'fees_dom_var': 3.4,
        'fees_int_fixed': 0.35,
        'fees_int_var': 3.9,
        'mercadopago_api_enabled': False,
    }

    def _migrate_mercadopago_account(self, context=None):
        """ COMPLETE ME """

        #cr.execute('SELECT id, mercadopago_account FROM res_company')
        #res = cr.fetchall()
        company_ids = self.env["res.company"].search([])
        for company in self.env['res.company'].browse(company_ids):
            company_id = company.id
            company_mercadopago_account = company.mercadopago_account
        #for (company_id, company_mercadopago_account) in res:
            if company_mercadopago_account:
                company_mercadopago_ids = self.search([('company_id', '=', company_id), ('provider', '=', 'mercadopago')], limit=1, context=context)
                if company_mercadopago_ids:
                    self.write( company_mercadopago_ids, {'mercadopago_email_account': company_mercadopago_account}, context=context)
                else:
                    mercadopago_view = self.env['ir.model.data'].get_object(cr, uid, 'payment_mercadopago', 'mercadopago_acquirer_button')
                    self.create({
                        'name': 'MercadoPago',
                        'provider': 'mercadopago',
                        'mercadopago_email_account': company_mercadopago_account,
                        'view_template_id': mercadopago_view.id,
                    }, context=context)
        return True

    def mercadopago_compute_fees(self, id, amount, currency_id, country_id, context=None):
        """ Compute mercadopago fees.

            :param float amount: the amount to pay
            :param integer country_id: an ID of a res.country, or None. This is
                                       the customer's country, to be compared to
                                       the acquirer company country.
            :return float fees: computed fees
        """
        acquirer = self.browse( id, context=context)
        if not acquirer.fees_active:
            return 0.0
        country = self.env['res.country'].browse( country_id, context=context)
        if country and acquirer.company_id.country_id.id == country.id:
            percentage = acquirer.fees_dom_var
            fixed = acquirer.fees_dom_fixed
        else:
            percentage = acquirer.fees_int_var
            fixed = acquirer.fees_int_fixed
        fees = (percentage / 100.0 * amount + fixed ) / (1 - percentage / 100.0)
        return fees

    def mercadopago_form_generate_values(self, id, partner_values, tx_values, context=None):
        base_url = self.pool['ir.config_parameter'].get_param( SUPERUSER_ID, 'web.base.url')
        acquirer = self.browse( id, context=context)

        print "mercadopago_form_generate_values: tx_values: ", tx_values
        print "partner_values:", partner_values

        MPago = False
        MPagoPrefId = False

        if acquirer.mercadopago_client_id and acquirer.mercadopago_secret_key:
            MPago = mercadopago.MP( acquirer.mercadopago_client_id, acquirer.mercadopago_secret_key )
            print "MPago: ", MPago
        else:
            error_msg = 'YOU MUST COMPLETE acquirer.mercadopago_client_id and acquirer.mercadopago_secret_key'
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        jsondump = ""

        if MPago:

            if acquirer.environment=="prod":
                MPago.sandbox_mode(False)
            else:
                MPago.sandbox_mode(True)

            MPagoToken = MPago.get_access_token()

            preference = {
                "items": [
                {
                    "title": "Orden Ecommerce "+ tx_values["reference"] ,
                    #"picture_url": "https://www.mercadopago.com/org-img/MP3/home/logomp3.gif",
                    "quantity": 1,
                    "currency_id":  tx_values['currency'] and tx_values['currency'].name or '',
                    "unit_price": tx_values["amount"],
                    #"category_id": "Categoría",
                }
                ]
                ,
                "payer": {
		            "name": partner_values["name"],
		            "surname": partner_values["first_name"],
		            "email": partner_values["email"],
#		            "date_created": "2015-01-29T11:51:49.570-04:00",
#		            "phone": {
#			            "area_code": "+5411",
#			            "number": partner_values["phone"]
#		            },
#		            "identification": {
#			            "type": "DNI",
#			            "number": "12345678"
#		            },
#		            "address": {
#			            "street_name": partner_values["address"],
#			            "street_number": "",
#			            "zip_code": partner_values["zip"]
#		            } contni
	            },
	            "back_urls": {
		            "success": '%s' % urlparse.urljoin( base_url, MercadoPagoController._return_url),
		            "failure": '%s' % urlparse.urljoin( base_url, MercadoPagoController._cancel_url),
		            "pending": '%s' % urlparse.urljoin( base_url, MercadoPagoController._return_url)
	            },
	            "auto_return": "approved",
#	            "payment_methods": {
#		            "excluded_payment_methods": [
#			            {
#				            "id": "amex"
#			            }
#		            ],
#		            "excluded_payment_types": [
#			            {
#				            "id": "ticket"
#			            }
#		            ],
#		            "installments": 24,
#		            "default_payment_method_id": '',
#		            "default_installments": '',
#	            },
#	            "shipments": {
#		            "receiver_address":
#		             {
#			            "zip_code": "1430",
#			            "street_number": 123,
#			            "street_name": "Calle Trece",
#			            "floor": 4,
#			            "apartment": "C"
#		            }
#	            },
	            "notification_url": '%s' % urlparse.urljoin( base_url, MercadoPagoController._notify_url),
	            "external_reference": tx_values["reference"],
	            "expires": True,
	            "expiration_date_from": "2015-01-29T11:51:49.570-04:00",
	            "expiration_date_to": "2015-02-28T11:51:49.570-04:00"
                }

            print "preference:", preference

            preferenceResult = MPago.create_preference(preference)

            print "preferenceResult: ", preferenceResult
            if 'response' in preferenceResult:
                if 'id' in preferenceResult['response']:
                    MPagoPrefId = preferenceResult['response']['id']
            else:
                error_msg = 'Returning response is:'
                error_msg+= json.dumps(preferenceResult, indent=2)
                _logger.error(error_msg)
                raise ValidationError(error_msg)


            if acquirer.environment=="prod":
                linkpay = preferenceResult['response']['init_point']
            else:
                linkpay = preferenceResult['response']['sandbox_init_point']

            jsondump = json.dumps( preferenceResult, indent=2 )

            print "linkpay:", linkpay
            print "jsondump:", jsondump
            print "MPagoPrefId: ", MPagoPrefId
            print "MPagoToken: ", MPagoToken


        mercadopago_tx_values = dict(tx_values)
        if MPagoPrefId:
            mercadopago_tx_values.update({
            'pref_id': MPagoPrefId,
#            'cmd': '_xclick',
#            'business': acquirer.mercadopago_email_account,
#            'item_name': tx_values['reference'],
#            'item_number': tx_values['reference'],
#            'amount': tx_values['amount'],
#            'currency_code': tx_values['currency'] and tx_values['currency'].name or '',
#            'address1': partner_values['address'],
#            'city': partner_values['city'],
#            'country': partner_values['country'] and partner_values['country'].name or '',
#            'state': partner_values['state'] and partner_values['state'].name or '',
#            'email': partner_values['email'],
#            'zip': partner_values['zip'],
#            'first_name': partner_values['first_name'],
#            'last_name': partner_values['last_name'],
#            'return': '%s' % urlparse.urljoin(base_url, MercadoPagoController._return_url),
#            'notify_url': '%s' % urlparse.urljoin(base_url, MercadoPagoController._notify_url),
#            'cancel_return': '%s' % urlparse.urljoin(base_url, MercadoPagoController._cancel_url),
            })

#        if acquirer.fees_active:
#            mercadopago_tx_values['handling'] = '%.2f' % mercadopago_tx_values.pop('fees', 0.0)
#        if mercadopago_tx_values.get('return_url'):
#            mercadopago_tx_values['custom'] = json.dumps({'return_url': '%s' % mercadopago_tx_values.pop('return_url')})
        return partner_values, mercadopago_tx_values

    def mercadopago_get_form_action_url(self, id, context=None):
        acquirer = self.browse( id, context=context)
        mercadopago_urls = self._get_mercadopago_urls( acquirer.environment, context=context)['mercadopago_form_url']
#        mercadopago_urls = mercadopago_urls + "?pref_id=" +
        print "mercadopago_get_form_action_url: ", mercadopago_urls
        return mercadopago_urls

    def _mercadopago_s2s_get_access_token(self, ids, context=None):
        """
        Note: see # see http://stackoverflow.com/questions/2407126/python-urllib2-basic-auth-problem
        for explanation why we use Authorization header instead of urllib2
        password manager
        """
        res = dict.fromkeys(ids, False)
        parameters = werkzeug.url_encode({'grant_type': 'client_credentials'})

        for acquirer in self.browse( ids, context=context):
            tx_url = self._get_mercadopago_urls( acquirer.environment)['mercadopago_rest_url']
            request = urllib2.Request(tx_url, parameters)

            # add other headers (https://developer.paypal.com/webapps/developer/docs/integration/direct/make-your-first-call/)
            request.add_header('Accept', 'application/json')
            request.add_header('Accept-Language', 'en_US')

            # add authorization header
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

    def _mercadopago_form_get_tx_from_data(self, data, context=None):
#        reference, txn_id = data.get('external_reference'), data.get('txn_id')
        reference, collection_id = data.get('external_reference'), data.get('collection_id')
        if not reference or not collection_id:
            error_msg = 'MercadoPago: received data with missing reference (%s) or collection_id (%s)' % (reference,collection_id)
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        # find tx -> @TDENOTE use txn_id ?
        tx_ids = self.env['payment.transaction'].search( [('reference', '=', reference)], context=context)
        if not tx_ids or len(tx_ids) > 1:
            error_msg = 'MercadoPago: received data for reference %s' % (reference)
            if not tx_ids:
                error_msg += '; no order found'
            else:
                error_msg += '; multiple order found'
            _logger.error(error_msg)
            raise ValidationError(error_msg)
        return self.browse( tx_ids[0], context=context)

    def _mercadopago_form_get_invalid_parameters(self, tx, data, context=None):
        invalid_parameters = []
        _logger.warning('Received a notification from MercadoLibre.')

        # TODO: txn_id: shoudl be false at draft, set afterwards, and verified with txn details
#        if tx.acquirer_reference and data.get('txn_id') != tx.acquirer_reference:
#            invalid_parameters.append(('txn_id', data.get('txn_id'), tx.acquirer_reference))
        # check what is buyed
#        if float_compare(float(data.get('mc_gross', '0.0')), (tx.amount + tx.fees), 2) != 0:
#            invalid_parameters.append(('mc_gross', data.get('mc_gross'), '%.2f' % tx.amount))  # mc_gross is amount + fees
#        if data.get('mc_currency') != tx.currency_id.name:
#            invalid_parameters.append(('mc_currency', data.get('mc_currency'), tx.currency_id.name))
#        if 'handling_amount' in data and float_compare(float(data.get('handling_amount')), tx.fees, 2) != 0:
#            invalid_parameters.append(('handling_amount', data.get('handling_amount'), tx.fees))
        # check buyer
#        if tx.partner_reference and data.get('payer_id') != tx.partner_reference:
#            invalid_parameters.append(('payer_id', data.get('payer_id'), tx.partner_reference))
        # check seller
#        if data.get('receiver_email') != tx.acquirer_id.mercadopago_email_account:
#            invalid_parameters.append(('receiver_email', data.get('receiver_email'), tx.acquirer_id.mercadopago_email_account))
#        if data.get('receiver_id') and tx.acquirer_id.mercadopago_seller_account and data['receiver_id'] != tx.acquirer_id.mercadopago_seller_account:
#            invalid_parameters.append(('receiver_id', data.get('receiver_id'), tx.acquirer_id.mercadopago_seller_account))

        return invalid_parameters

#From https://developers.mercadopago.com/documentacion/notificaciones-de-pago
#
#approved 	El pago fue aprobado y acreditado.
#pending 	El usuario no completó el proceso de pago.
#in_process	El pago está siendo revisado.
#rejected 	El pago fue rechazado. El usuario puede intentar nuevamente.
#refunded (estado terminal) 	El pago fue devuelto al usuario.
#cancelled (estado terminal) 	El pago fue cancelado por superar el tiempo necesario para realizar el pago o por una de las partes.
#in_mediation 	Se inició una disputa para el pago.
#charged_back (estado terminal) 	Se realizó un contracargo en la tarjeta de crédito.
    #called by Trans.form_feedback(...) > %s_form_validate(...)
    def _mercadopago_form_validate(self, tx, data, context=None):
        status = data.get('collection_status')
        data = {
            'acquirer_reference': data.get('external_reference'),
            'mercadopago_txn_type': data.get('payment_type')
        }
        if status in ['approved', 'processed']:
            _logger.info('Validated MercadoPago payment for tx %s: set as done' % (tx.reference))
            data.update(state='done', date_validate=data.get('payment_date', fields.datetime.now()))
            return tx.write(data)
        elif status in ['pending', 'in_process','in_mediation']:
            _logger.info('Received notification for MercadoPago payment %s: set as pending' % (tx.reference))
            data.update(state='pending', state_message=data.get('pending_reason', ''))
            return tx.write(data)
        elif status in ['cancelled','refunded','charged_back','rejected']:
            _logger.info('Received notification for MercadoPago payment %s: set as cancelled' % (tx.reference))
            data.update(state='cancel', state_message=data.get('cancel_reason', ''))
            return tx.write(data)
        else:
            error = 'Received unrecognized status for MercadoPago payment %s: %s, set as error' % (tx.reference, status)
            _logger.info(error)
            data.update(state='error', state_message=error)
            return tx.write(data)

    # --------------------------------------------------
    # SERVER2SERVER RELATED METHODS
    # --------------------------------------------------

    def _mercadopago_try_url(self, request, tries=3, context=None):
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
                if tries and res and json.loads(res)['name'] == 'INTERNAL_SERVICE_ERROR':
                    _logger.warning('Failed contacting MercadoPago, retrying (%s remaining)' % tries)
            tries = tries - 1
        if not res:
            pass
            # raise openerp.exceptions.
        result = res.read()
        res.close()
        return result

    def _mercadopago_s2s_send(self, values, cc_values, context=None):
        """
         .. versionadded:: pre-v8 saas-3
         .. warning::

            Experimental code. You should not use it before OpenERP v8 official
            release.
        """
        tx_id = self.create( values, context=context)
        tx = self.browse( tx_id, context=context)

        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer %s' % tx.acquirer_id._mercadopago_s2s_get_access_token()[tx.acquirer_id.id],
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

        request = urllib2.Request('https://api.sandbox.paypal.com/v1/payments/payment', data, headers)
        result = self._mercadopago_try_url(request, tries=3, context=context)
        return (tx_id, result)

    def _mercadopago_s2s_get_invalid_parameters(self, tx, data, context=None):
        """
         .. versionadded:: pre-v8 saas-3
         .. warning::

            Experimental code. You should not use it before OpenERP v8 official
            release.
        """
        invalid_parameters = []
        return invalid_parameters

    def _mercadopago_s2s_validate(self, tx, data, context=None):
        """
         .. versionadded:: pre-v8 saas-3
         .. warning::

            Experimental code. You should not use it before OpenERP v8 official
            release.
        """
        values = json.loads(data)
        status = values.get('state')
        if status in ['approved']:
            _logger.info('Validated Mercadopago s2s payment for tx %s: set as done' % (tx.reference))
            tx.write({
                'state': 'done',
                'date_validate': values.get('udpate_time', fields.datetime.now()),
                'mercadopago_txn_id': values['id'],
            })
            return True
        elif status in ['pending', 'expired']:
            _logger.info('Received notification for MercadoPago s2s payment %s: set as pending' % (tx.reference))
            tx.write({
                'state': 'pending',
                # 'state_message': data.get('pending_reason', ''),
                'mercadopago_txn_id': values['id'],
            })
            return True
        else:
            error = 'Received unrecognized status for MercadoPago s2s payment %s: %s, set as error' % (tx.reference, status)
            _logger.info(error)
            tx.write({
                'state': 'error',
                # 'state_message': error,
                'mercadopago_txn_id': values['id'],
            })
            return False

    def _mercadopago_s2s_get_tx_status(self, tx, context=None):
        """
         .. versionadded:: pre-v8 saas-3
         .. warning::

            Experimental code. You should not use it before OpenERP v8 official
            release.
        """
        # TDETODO: check tx.mercadopago_txn_id is set
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer %s' % tx.acquirer_id._mercadopago_s2s_get_access_token()[tx.acquirer_id.id],
        }
        url = 'https://api.sandbox.paypal.com/v1/payments/payment/%s' % (tx.mercadopago_txn_id)
        request = urllib2.Request(url, headers=headers)
        data = self._mercadopago_try_url(request, tries=3, context=context)
        return self.s2s_feedback( tx.id, data, context=context)
