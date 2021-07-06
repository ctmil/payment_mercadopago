# -*- coding: utf-'8' "-*-"

try:
    import simplejson as json
except ImportError:
    import json
import logging
from urllib.parse import urljoin
import datetime

import mercadopago

from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.addons.payment_mercadopago.controllers.main import MercadoPagoController
from odoo import osv, fields, models, api

_logger = logging.getLogger(__name__)
from dateutil.tz import *

dateformat = "%Y-%m-%dT%H:%M:%S."
dateformatmilis = "%f"
dateformatutc = "%z"


class AcquirerMercadopago(models.Model):
    _inherit = 'payment.acquirer'

    provider = fields.Selection(selection_add=[('mercadopago', 'MercadoPago')])
    mercadopago_api_access_token = fields.Char('Access Token')

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
        country = self.env['res.country'].browse(country_id)
        if country and acquirer.company_id.country_id.id == country.id:
            percentage = acquirer.fees_dom_var
            fixed = acquirer.fees_dom_fixed
        else:
            percentage = acquirer.fees_int_var
            fixed = acquirer.fees_int_fixed
        fees = (percentage / 100.0 * amount + fixed) / (1 - percentage / 100.0)
        return fees

    def mercadopago_dateformat(self, date):
        stf = date.strftime(dateformat)
        stf_utc_milis = date.strftime(dateformatmilis)
        stf_utc_milis = stf_utc_milis[0] + stf_utc_milis[1] + stf_utc_milis[2]
        stf_utc_zone = date.strftime(dateformatutc)
        stf_utc_zone = stf_utc_zone[0] + stf_utc_zone[1] + stf_utc_zone[2] + ":" + stf_utc_zone[3] + stf_utc_zone[4]
        stf_utc = stf + stf_utc_milis + stf_utc_zone
        return stf_utc

    @api.multi
    def mercadopago_form_generate_values(self, values):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        tx_values = dict(values)
        transaction = self.env["payment.transaction"].search([("reference", "=", tx_values["reference"])])
        amount = tx_values["amount"]
        MPagoPrefId = False
        if not self.mercadopago_api_access_token:
            error_msg = 'YOU MUST COMPLETE mercadopago_api_access_token'
            _logger.error(error_msg)
            raise ValidationError(error_msg)
        MPago = mercadopago.SDK(self.mercadopago_api_access_token)
        mercadopago_tx_values = dict(tx_values)
        preference = {
            "items": [
                {
                    "title": "Orden Ecommerce " + tx_values["reference"],
                    "quantity": 1,
                    "currency_id": tx_values['currency'] and tx_values['currency'].name or '',
                    "unit_price": amount,
                }
            ],
            "payer": {
                "name": tx_values.get("partner_name"),
                "email": tx_values.get("partner_email"),
                "phone": {
                    "number": tx_values.get("partner_phone")
                },
                "address": {
                    "street_name": tx_values.get("partner_address"),
                    "street_number": "",
                    "zip_code": tx_values.get("partner_zip"),
                }
            },
            "back_urls": {
                "success": '%s' % urljoin(base_url, MercadoPagoController._return_url),
                "failure": '%s' % urljoin(base_url, MercadoPagoController._cancel_url),
                "pending": '%s' % urljoin(base_url, MercadoPagoController._return_url)
            },
            "auto_return": "approved",
            "notification_url": '%s' % urljoin(base_url, MercadoPagoController._notify_url),
            "external_reference": tx_values["reference"],
            "expires": True,
            "expiration_date_from": self.mercadopago_dateformat(
                datetime.datetime.now(tzlocal()) - datetime.timedelta(days=1)),
            "expiration_date_to": self.mercadopago_dateformat(
                datetime.datetime.now(tzlocal()) + datetime.timedelta(days=31))
        }
        preferenceResult = MPago.preference().create(preference)
        if 'response' in preferenceResult:
            if 'error' in preferenceResult['response']:
                error_msg = 'Returning response is:'
                error_msg += json.dumps(preferenceResult, indent=2)
                _logger.error(error_msg)
                raise ValidationError(error_msg)
            if 'id' in preferenceResult['response']:
                MPagoPrefId = preferenceResult['response']['id']
        else:
            error_msg = 'Returning response is:'
            error_msg += json.dumps(preferenceResult, indent=2)
            _logger.error(error_msg)
            raise ValidationError(error_msg)
        if self.environment == "prod":
            linkpay = preferenceResult['response']['init_point']
        else:
            linkpay = preferenceResult['response']['sandbox_init_point']
        if MPagoPrefId:
            transaction.write({"acquirer_reference": MPagoPrefId})
            mercadopago_tx_values.update({
                'pref_id': MPagoPrefId,
                'link_pay': linkpay
            })
        _logger.info(mercadopago_tx_values)
        return mercadopago_tx_values

    def mercadopago_get_form_action_url(self):
        return ""

    @api.model
    def mercadopago_get_reference(self, payment_id=None, topic="payment"):
        reference = None
        if not payment_id:
            return reference
        mps = self.search([('provider', '=', 'mercadopago'), ('mercadopago_api_access_token', '!=', False)])
        for mp in mps:
            data = mp._mercadopago_get_data(payment_id=payment_id, topic=topic)
            if data and 'external_reference' in data:
                return data['external_reference']
        return reference

    @api.multi
    def _mercadopago_get_data(self, payment_id=None, reference=None, topic="payment"):
        self.ensure_one()
        assert topic in ["payment", "merchant_order"], "Topic debe estar entre payment, merchant_order"
        data = None
        MPago = mercadopago.SDK(self.mercadopago_api_access_token)
        payment_result = {}
        if reference:
            if topic == "payment":
                payment_result = MPago.payment().search({"external_reference": reference})
            else:
                payment_result = MPago.merchant_order().search({"external_reference": reference})
        else:
            if topic == "payment":
                payment_result = MPago.payment().get(payment_id)
            else:
                payment_result = MPago.merchant_order().get(payment_id)
        if payment_result and 'response' in payment_result:
            _results = []
            if 'results' in payment_result['response']:
                _results = payment_result['response']['results']
            else:
                _results.append(payment_result['response'])
            for result in _results:
                _logger.info(result)
                _status = result['status']
                if 'order' in result:
                    _order_id = result['order']['id']
                    merchant_order = MPago.merchant_order().get(_order_id)
                    data = {
                        'id': result['id'],
                        'topic': 'payment',
                        'collection_status': result['status'],
                        'external_reference': result['external_reference'],
                        'payment_type': result['payment_type_id'],
                        'merchant_order_id': _order_id
                    }
                    if 'response' in merchant_order and 'preference_id' in merchant_order['response']:
                        data['pref_id'] = merchant_order['response']['preference_id']
                    return data
        return data


class TxMercadoPago(models.Model):
    _inherit = 'payment.transaction'

    mercadopago_txn_id = fields.Char('Transaction ID', index=True)
    mercadopago_txn_type = fields.Char('Transaction type', index=True)
    mercadopago_txn_preference_id = fields.Char(string='Mercadopago Preference id', index=True)
    mercadopago_txn_merchant_order_id = fields.Char(string='Mercadopago Merchant Order id', index=True)

    def action_mercadopago_check_status(self):
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
                # _logger.info(data)
                if (data):
                    tx._mercadopago_form_validate(dict(data))
            except Exception as e:
                error_msg = 'Reference: ' + str(acquirer_reference) + ' not found,'
                error_msg += '\n' + 'or Transaction was cancelled.'
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
            error_msg = 'MercadoPago: received data with missing reference (%s) or collection_id (%s)' % (
            reference, collection_id)
            _logger.error(error_msg)
            raise ValidationError(error_msg)

        # find tx -> @TDENOTE use txn_id ?
        tx_ids = self.env['payment.transaction'].search([('reference', '=', reference)])
        if not tx_ids or len(tx_ids) > 1:
            error_msg = 'MercadoPago: received data for reference %s' % (reference)
            if not tx_ids:
                error_msg += '; no order found'
            else:
                error_msg += '; multiple order found'
            _logger.error(error_msg)
            raise ValidationError(error_msg)
        return tx_ids

    # From https://developers.mercadopago.com/documentacion/notificaciones-de-pago
    #
    # approved 	El pago fue aprobado y acreditado.
    # pending 	El usuario no completó el proceso de pago.
    # in_process	El pago está siendo revisado.
    # rejected 	El pago fue rechazado. El usuario puede intentar nuevamente.
    # refunded (estado terminal) 	El pago fue devuelto al usuario.
    # cancelled (estado terminal) 	El pago fue cancelado por superar el tiempo necesario para realizar el pago o por una de las partes.
    # in_mediation 	Se inició una disputa para el pago.
    # charged_back (estado terminal) 	Se realizó un contracargo en la tarjeta de crédito.
    # called by Trans.form_feedback(...) > %s_form_validate(...)
    def _mercadopago_form_validate(self, data):
        # IPN style
        f_data = data
        topic = f_data.get('topic') or f_data.get('type')
        payment_id = f_data.get('id') or f_data.get('data.id')
        # DPN style
        external_reference = f_data.get('external_reference')

        if (topic in ["payment"] and payment_id and self.acquirer_id):
            # IPN based on payment id, preferred...
            res = self.acquirer_id._mercadopago_get_data(payment_id=payment_id)
            if (res):
                f_data.update(res)
            external_reference = f_data.get('external_reference')
        elif (external_reference):
            # DPN based on payment id, preferred...
            res = self.acquirer_id._mercadopago_get_data(reference=external_reference)
            if (res):
                f_data.update(res)
            payment_id = f_data.get('id')

        # REST OF THE FIELDS:
        status = f_data.get('collection_status')
        payment_type = f_data.get('payment_type')
        pref_id = f_data.get('pref_id')
        merchant_order_id = f_data.get('merchant_order_id')

        _logger.info("_mercadopago_form_validate: external_reference: " + str(external_reference))

        # BUILD data to write into Transaction fields
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

        # _logger.info("Final data:")
        # _logger.info(data)
        if status in ['approved', 'processed']:
            _logger.info('Validated MercadoPago payment for tx %s: set as done' % (self.reference))
            if (self.state not in ['done']):
                data.update(state='done', date=data.get('payment_date', fields.datetime.now()))
            self.sudo()._set_transaction_done()
            return self.sudo().write(data)
        elif status in ['pending', 'in_process', 'in_mediation']:
            _logger.info('Received notification for MercadoPago payment %s: set as pending' % (self.reference))
            if (self.state not in ['pending']):
                data.update(state='pending', state_message=data.get('pending_reason', ''))
            self.sudo()._set_transaction_pending()
            return self.sudo().write(data)
        elif status in ['cancelled', 'refunded', 'charged_back', 'rejected']:
            _logger.info('Received notification for MercadoPago payment %s: set as cancelled' % (self.reference))
            if (self.state not in ['cancel']):
                data.update(state='cancel', state_message=data.get('cancel_reason', ''))
            self.sudo()._set_transaction_cancel()
            return self.sudo().write(data)
        else:
            error = 'Received unrecognized status for MercadoPago payment %s: %s, set as error' % (
            self.reference, status)
            _logger.info(error)
            data.update(state='error', state_message=error)
            self.sudo()._set_transaction_cancel()
            return self.sudo().write(data)
