# -*- coding: utf-'8' "-*-"

import base64
try:
    import simplejson as json
except ImportError:
    import json
import logging
from urllib.parse import urlparse
from urllib.parse import urljoin
import werkzeug.urls
from urllib.request import urlopen
import datetime
import requests
import re

from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.addons.payment_mercadopago.controllers.main import MercadoPagoController
from odoo import osv, fields, models, api
from odoo.tools.float_utils import float_compare
from odoo import SUPERUSER_ID

_logger = logging.getLogger(__name__)
from dateutil.tz import *

dateformat="%Y-%m-%dT%H:%M:%S."
dateformatmilis="%f"
dateformatutc="%z"

from odoo.addons.payment_mercadopago.mercadopago import mercadopago

class AcquirerMercadopago(models.Model):
    _inherit = 'payment.acquirer'

    def _get_mercadopago_urls(self, environment):
        """ MercadoPago URLS """
        if environment == 'prod':
            return {
                'mercadopago_form_url': 'https://www.mercadopago.com/mla/checkout/pay',
                'mercadopago_rest_url': 'https://api.mercadolibre.com/oauth/token',
            }
        else:
            return {
                'mercadopago_form_url': 'https://sandbox.mercadopago.com/mla/checkout/pay',
                'mercadopago_rest_url': 'https://api.sandbox.mercadolibre.com/oauth/token',
            }

    def _get_providers(self, context=None):
        providers = super(AcquirerMercadopago, self)._get_providers(cr, uid, context=context)
        providers.append(['mercadopago', 'MercadoPago'])
        return providers

    def _get_feature_support(self):
        """Get advanced feature support by provider.

        Each provider should add its technical in the corresponding
        key for the following features:
            * fees: support payment fees computations
            * authorize: support authorizing payment (separates
                         authorization and capture)
            * tokenize: support saving payment data in a payment.tokenize
                        object
        """
        res = super(AcquirerMercadopago, self)._get_feature_support()
        #res['tokenize'].append('mercadopago')
        return res

    provider = fields.Selection(selection_add=[('mercadopago', 'MercadoPago')])
    #mercadopago_client_id = fields.Char('MercadoPago Client Id',required_if_provider='mercadopago')
    mercadopago_client_id = fields.Char('MercadoPago Client Id', size=256)
    #mercadopago_secret_key = fields.Char('MercadoPago Secret Key',required_if_provider='mercadopago')
    mercadopago_secret_key = fields.Char('MercadoPago Secret Key', size=256)

    #mercadopago_email_account = fields.Char('MercadoPago Email ID', required_if_provider='mercadopago')
    mercadopago_email_account = fields.Char('MercadoPago Email ID', size=256)

    mercadopago_seller_account = fields.Char(
            'MercadoPago Merchant ID',
            size=256,
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

    def mercadopago_compute_fees(self, amount, currency_id, country_id):
        """ Compute mercadopago fees.

            :param float amount: the amount to pay
            :param integer country_id: an ID of a res.country, or None. This is
                                       the customer's country, to be compared to
                                       the acquirer company country.
            :return float fees: computed fees
        """
        acquirer = self
        if not acquirer.fees_active:
            return 0.0
        country = self.env['res.country'].browse( country_id)
        if country and acquirer.company_id.country_id.id == country.id:
            percentage = acquirer.fees_dom_var
            fixed = acquirer.fees_dom_fixed
        else:
            percentage = acquirer.fees_int_var
            fixed = acquirer.fees_int_fixed
        fees = (percentage / 100.0 * amount + fixed ) / (1 - percentage / 100.0)
        return fees

    def mercadopago_dateformat(self, date):
        stf = date.strftime(dateformat)
        stf_utc_milis = date.strftime(dateformatmilis)
        stf_utc_milis = stf_utc_milis[0]+stf_utc_milis[1]+stf_utc_milis[2]
        stf_utc_zone = date.strftime(dateformatutc)
        stf_utc_zone = stf_utc_zone[0]+stf_utc_zone[1]+stf_utc_zone[2]+":"+stf_utc_zone[3]+stf_utc_zone[4]
        stf_utc = stf+stf_utc_milis+stf_utc_zone
        return stf_utc

    def make_path(self, path, params={}):
        # Making Path and add a leading / if not exist
        if not (re.search("^http", path)):
            if not (re.search("^\/", path)):
                path = "/" + path
            path = self.API_ROOT_URL + path
        if params:
            path = path + "?" + urlencode(params)
        return path


    def mercadopago_form_generate_values(self, values):

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        acquirer = self

        tx_values = dict(values)
        _logger.info(tx_values)
        saleorder_obj = self.env['sale.order']
        saleorderline_obj = self.env['sale.order.line']

        topic = values.get('topic')
        op_id = values.get('id')

        reference = None
        sorder_s = None
        if (topic and op_id):
            pass;
        elif ("reference" in tx_values):
            reference = tx_values["reference"]
            sorder_s = saleorder_obj.search([ ('name','=',tx_values["reference"]) ] )

        shipments = ''
        amount = tx_values["amount"]
        melcatid = False
        if (sorder_s):
            if (len(sorder_s.order_line)>0):
                firstprod = sorder_s.order_line[0].product_id
            if (melcatid):
                for oline in  sorder_s.order_line:
                    if (str(oline.product_id.name.encode("utf-8")) == str('MercadoEnvíos')):
                        melcatidrequest = 'https://api.mercadolibre.com/categories/'+str(melcatid)+'/shipping'
                        headers = {'Accept': 'application/json', 'Content-type':'application/json'}
                        uri = self.make_path(melcatidrequest)
                        response = requests.get(uri, params='', headers=headers)
                        if response.status_code == requests.codes.ok:
                            rdims = response.json()
                            dims = str(rdims["height"])+str("x")+str(rdims["width"])+str("x")+str(rdims["length"])+str(",")+str(rdims["weight"])
                            shipments = {
                                "mode": "me2",
                                #"dimensions": "30x30x30,500",
                                "dimensions": dims,
                                "zip_code": tx_values.get("partner_zip"),
                            }

        MPago = False
        MPagoPrefId = False

        if acquirer.mercadopago_client_id and acquirer.mercadopago_secret_key:
            MPago = mercadopago.MP( acquirer.mercadopago_client_id, acquirer.mercadopago_secret_key )
            #_logger.info( MPago )
        else:
            error_msg = 'YOU MUST COMPLETE acquirer.mercadopago_client_id and acquirer.mercadopago_secret_key'
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        jsondump = ""

        MPagoToken = False
        if MPago:

            if acquirer.state=="enabled":
                MPago.sandbox_mode(False)
            elif acquirer.state=="disabled":
                return {}
            else:
                MPago.sandbox_mode(True)

            MPagoToken = MPago.identificationtype.get_access_token()

            if (MPagoToken):
                self.mercadopago_api_access_token = MPagoToken
            #_logger.info("MPagoToken:"+str(self.mercadopago_api_access_token))

            #mpago = https://api.mercadolibre.com/categories/MLA371926/shipping
            #cost: https://api.mercadolibre.com/users/:user_id/shipping_options?category_id=:category_id&dimensions=:dim&zip_code=13565905
            #request

            #{ "category_id": "MLA371926", "height": 30, "width": 30, "length": 30, "weight": 650 }

        mercadopago_tx_values = dict(tx_values)

        if (not MPagoToken):
            return mercadopago_tx_values

        if (reference):
            preference = {
                "items": [
                {
                    "title": "Orden Ecommerce "+ tx_values["reference"],
                    #"picture_url": "https://www.mercadopago.com/org-img/MP3/home/logomp3.gif",
                    "quantity": 1,
                    "currency_id":  tx_values['currency'] and tx_values['currency'].name or '',
                    "unit_price": amount,
                    #"categoryid": "Categoría",
                }
                ]
                ,
                "payer": {
		            "name": tx_values.get("partner_name"),
		            #"surname": tx_values.get("partner_first_name"),
		            "email": tx_values.get("partner_email"),
#		            "date_created": "2015-01-29T11:51:49.570-04:00",
		            "phone": {
#			            "area_code": "+5411",
			            "number": tx_values.get("partner_phone")
		            },
#		            "identification": {
#			            "type": "DNI",
#			            "number": "12345678"
#		            },
		            "address": {
			            "street_name": tx_values.get("partner_address"),
			            "street_number": "",
			            "zip_code": tx_values.get("partner_zip"),
		            }
	            },
	            "back_urls": {
		            "success": '%s' % urljoin( base_url, MercadoPagoController._return_url),
		            "failure": '%s' % urljoin( base_url, MercadoPagoController._cancel_url),
		            "pending": '%s' % urljoin( base_url, MercadoPagoController._return_url)
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
	            "notification_url": '%s' % urljoin( base_url, MercadoPagoController._notify_url),
	            "external_reference": tx_values["reference"],
	            "expires": True,
	            "expiration_date_from": self.mercadopago_dateformat( datetime.datetime.now(tzlocal())-datetime.timedelta(days=1) ),
	            "expiration_date_to": self.mercadopago_dateformat( datetime.datetime.now(tzlocal())+datetime.timedelta(days=31) )
                }

            if (len(shipments)):
                preference["shipments"] = shipments

            preferenceResult = MPago.preference.create(preference)

            if 'response' in preferenceResult:
                if 'error' in preferenceResult['response']:
                    error_msg = 'Returning response is:'
                    error_msg+= json.dumps(preferenceResult, indent=2)
                    _logger.error(error_msg)
                    raise ValidationError(error_msg)

                if 'id' in preferenceResult['response']:
                    MPagoPrefId = preferenceResult['response']['id']
            else:
                error_msg = 'Returning response is:'
                error_msg+= json.dumps(preferenceResult, indent=2)
                _logger.error(error_msg)
                raise ValidationError(error_msg)


            if acquirer.state=="enabled":
                linkpay = preferenceResult['response']['init_point']
            elif acquirer.state=="disabled":
                return {}
            else:
                linkpay = preferenceResult['response']['sandbox_init_point']

            jsondump = json.dumps( preferenceResult, indent=2 )

        if (not reference):
            payment_info = MPago.payment.get(op_id)

        if MPagoPrefId:
            mercadopago_tx_values.update({
                'pref_id': MPagoPrefId,
                'link_pay': linkpay
            })

        _logger.info(mercadopago_tx_values)
        return mercadopago_tx_values

    def mercadopago_get_form_action_url(self):
        environment = 'prod' if self.state == 'enabled' else 'test'
        return self._get_mercadopago_urls(environment)['mercadopago_form_url']

    def _mercadopago_s2s_get_access_token(self, ids, context=None):
        """
        Note: see # see http://stackoverflow.com/questions/2407126/python-urllib2-basic-auth-problem
        for explanation why we use Authorization header instead of urllib2
        password manager
        """
        res = dict.fromkeys(ids, False)
        parameters = werkzeug.url_encode({'grant_type': 'client_credentials'})

        for acquirer in self.browse( ids, context=context):
            environment = 'prod' if acquirer.state == 'enabled' else 'test'
            tx_url = self._get_mercadopago_urls( environment)['mercadopago_rest_url']
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

    @api.model
    def mercadopago_get_reference(self, payment_id=None ):
        reference = None
        if (not payment_id):
            return reference
        mps = self.search([('provider','=','mercadopago'),('mercadopago_client_id','!=',False),('mercadopago_secret_key','!=',False)])
        for mp in mps:
            data = mp._mercadopago_get_data(payment_id=payment_id)
            if (data and ('external_reference' in data) ):
                return data['external_reference']
        return reference


    def _mercadopago_get_data(self, payment_id=None, reference=None ):
        data = None
        for acquirer in self:
            MPago = False
            MPagoPrefId = False

            if acquirer.mercadopago_client_id and acquirer.mercadopago_secret_key:
                MPago = mercadopago.MP( acquirer.mercadopago_client_id, acquirer.mercadopago_secret_key )
                #_logger.info( MPago )
            else:
                error_msg = 'YOU MUST COMPLETE acquirer.mercadopago_client_id and acquirer.mercadopago_secret_key'
                _logger.error(error_msg)
                #raise ValidationError(error_msg)

            jsondump = ""

            MPagoToken = False
            if MPago:
                if acquirer.state=="enabled":
                    MPago.sandbox_mode(False)
                elif acquirer.state=="disabled":
                    return {}
                else:
                    MPago.sandbox_mode(True)

                MPagoToken = MPago.identificationtype.get_access_token()

                if (MPagoToken):
                    acquirer.mercadopago_api_access_token = MPagoToken
                #_logger.info("MPagoToken:"+str(acquirer.mercadopago_api_access_token))
                #payment_result = MPago.search_payment( _filters )
                search_uri = ''
                if (reference):
                    search_uri = '/v1/payments/search?'+'external_reference='+reference+'&access_token='+acquirer.mercadopago_api_access_token
                else:
                    search_uri = '/v1/payments/'+str(payment_id)+'?access_token='+acquirer.mercadopago_api_access_token
                #_logger.info(search_uri)
                payment_result = MPago.genericcall.get( search_uri )
                #_logger.info(payment_result)
                if (payment_result and 'response' in payment_result):
                    _results = []
                    if ('results' in payment_result['response']):
                        _results = payment_result['response']['results']
                    else:
                        _results.append( payment_result['response'] )
                    #_logger.info(_results)
                    for result in _results:
                        _logger.info(result)
                        _status = result['status']
                        if ('order' in result):
                            _order_id = result['order']['id']
                            #_order_uri = '/merchant_orders/'+str(_order_id)+'?access_token='+acquirer.mercadopago_api_access_token
                            #_logger.info(_order_uri)
                            merchant_order = MPago.merchantorder.get(_order_id)
                            #_logger.info(merchant_order)
                            data = {}
                            data['collection_status'] = result['status']
                            data['external_reference'] = result['external_reference']
                            data['payment_type'] = result['payment_type_id']
                            data['id'] = result['id']
                            data['topic'] = 'payment'
                            data['merchant_order_id'] = _order_id
                            if ('response' in merchant_order and 'preference_id' in merchant_order['response'] ):
                                data['pref_id'] = merchant_order['response']['preference_id']
                            #_logger.info(data)
                            return data
        return data


class TxMercadoPago(models.Model):
    _inherit = 'payment.transaction'

    mercadopago_txn_id = fields.Char('Transaction ID', index=True)
    mercadopago_txn_type = fields.Char('Transaction type', index=True)
    mercadopago_txn_preference_id = fields.Char(string='Mercadopago Preference id', index=True)
    mercadopago_txn_merchant_order_id = fields.Char(string='Mercadopago Merchant Order id', index=True)

    def _get_provider(self):
        for tx in self:
            tx.mercadopago_txn_provider = tx.acquirer_id.provider

    mercadopago_txn_provider = fields.Char(string="Provider",compute=_get_provider )

    def _get_pref_id_from_order( self, order_id ):

        return ''

    def action_mercadopago_check_status( self ):
        data = {}
        _logger.info("action_mercadopago_check_status")
        for tx in self:
            acquirer_reference = tx.reference
            if (tx.acquirer_reference):
                acquirer_reference = tx.acquirer_reference
            else:
                tx.acquirer_reference = tx.reference

            try:
                data = tx.acquirer_id._mercadopago_get_data(reference=acquirer_reference)
                #_logger.info(data)
                if (data):
                    tx._mercadopago_form_validate(dict(data))
            except Exception as e:
                error_msg = 'Reference: '+str(acquirer_reference)+' not found,'
                error_msg+= '\n'+'or Transaction was cancelled.'
                _logger.error(e, exc_info=True)
                raise ValidationError(e)

        return data

    # --------------------------------------------------
    # FORM RELATED METHODS
    # --------------------------------------------------
    @api.model
    def _mercadopago_form_get_tx_from_data(self, data, context=None):
#        reference, txn_id = data.get('external_reference'), data.get('txn_id')
        reference, collection_id = data.get('external_reference'), data.get('collection_id')
        if (not reference and not collection_id):
            error_msg = 'MercadoPago: received data with missing reference (%s) or collection_id (%s)' % (reference,collection_id)
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        # find tx -> @TDENOTE use txn_id ?
        tx_ids = self.env['payment.transaction'].search( [('reference', '=', reference)])
        if not tx_ids or len(tx_ids) > 1:
            error_msg = 'MercadoPago: received data for reference %s' % (reference)
            if not tx_ids:
                error_msg += '; no order found'
            else:
                error_msg += '; multiple order found'
            _logger.error(error_msg)
            raise ValidationError(error_msg)
        return tx_ids

    def _mercadopago_form_get_invalid_parameters(self, data):
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
    def _mercadopago_form_validate(self, data):
        #IPN style
        f_data = data
        topic = f_data.get('topic') or f_data.get('type')
        payment_id = f_data.get('id') or f_data.get('data.id')
        #DPN style
        external_reference = f_data.get('external_reference')

        if (topic in ["payment"] and payment_id and self.acquirer_id):
            #IPN based on payment id, preferred...
            res = self.acquirer_id._mercadopago_get_data(payment_id=payment_id)
            if (res):
                f_data.update( res )
            external_reference = f_data.get('external_reference')
        elif (external_reference):
            #DPN based on payment id, preferred...
            res = self.acquirer_id._mercadopago_get_data(reference=external_reference)
            if (res):
                f_data.update( res )
            payment_id = f_data.get('id')

        #REST OF THE FIELDS:
        status = f_data.get('collection_status')
        payment_type = f_data.get('payment_type')
        pref_id = f_data.get('pref_id')
        merchant_order_id = f_data.get('merchant_order_id')

        _logger.info("_mercadopago_form_validate: external_reference: " +str(external_reference))

        #BUILD data to write into Transaction fields
        data = {}
        if (payment_type and external_reference):
            data.update({
                'acquirer_reference': external_reference,
                'mercadopago_txn_type': payment_type
            })

        if (merchant_order_id):
            data["mercadopago_txn_merchant_order_id"] = merchant_order_id

        if (pref_id):
            data['mercadopago_txn_preference_id'] = str(pref_id)

        if (payment_id):
            data['mercadopago_txn_id'] = str(payment_id)

        #_logger.info("Final data:")
        #_logger.info(data)
        if status in ['approved', 'processed']:
            _logger.info('Validated MercadoPago payment for tx %s: set as done' % (self.reference))
            if (self.state not in ['done']):
                data.update(state='done', date=data.get('payment_date', fields.datetime.now()))
            self.sudo()._set_transaction_done()
            return self.sudo().write(data)
        elif status in ['pending', 'in_process','in_mediation']:
            _logger.info('Received notification for MercadoPago payment %s: set as pending' % (self.reference))
            if (self.state not in ['pending']):
                data.update(state='pending', state_message=data.get('pending_reason', ''))
            self.sudo()._set_transaction_pending()
            return self.sudo().write(data)
        elif status in ['cancelled','refunded','charged_back','rejected']:
            _logger.info('Received notification for MercadoPago payment %s: set as cancelled' % (self.reference))
            if (self.state not in ['cancel']):
                data.update(state='cancel', state_message=data.get('cancel_reason', ''))
            self.sudo()._set_transaction_cancel()
            return self.sudo().write(data)
        else:
            error = 'Received unrecognized status for MercadoPago payment %s: %s, set as error' % (self.reference, status)
            _logger.info(error)
            data.update(state='error', state_message=error)
            self.sudo()._set_transaction_cancel()
            return self.sudo().write(data)

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
        tx = self.create( values, context=context)
        tx_id = tx.id

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
                        'first_name': '',
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
                'date': values.get('udpate_time', fields.datetime.now()),
                'mercadopago_txn_id': values['id'],
            })
            self._set_transaction_done()
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
