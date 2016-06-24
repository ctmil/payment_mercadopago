# -*- coding: utf-8 -*-

import logging
import pprint
import werkzeug

from openerp import http, SUPERUSER_ID, _
from openerp.http import request
from openerp.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class MercadoPagoController(http.Controller):
    _notify_url = '/payment/mercadopago/ipn/'
    _return_url = '/payment/mercadopago/dpn/'
    _cancel_url = '/payment/mercadopago/cancel/'

    def _get_return_url(self, **post):
        """ Extract the return URL from the data coming from MercadoPago. """
        if post.get('collection_status') in ['approved']:
            return request.registry['ir.config_parameter'] \
                .get_param(request.cr,
                           SUPERUSER_ID,
                           'web.site.payment.approved.url', '/')
        else:
            return request.registry['ir.config_parameter'] \
                .get_param(request.cr,
                           SUPERUSER_ID,
                           'web.site.payment.cancelled.url', '/')

    def mercadopago_validate_data(self, **post):
        """ MercadoPago IPN: three steps validation to ensure data correctness

         - step 1: return an empty HTTP 200 response -> will be done at the end
           by returning ''
         - step 2: POST the complete, unaltered message back to MercadoPago (
           preceded by cmd=_notify-validate), with same encoding
         - step 3: mercadopago send either VERIFIED or INVALID (single word)

        Once data is validated, process it. """

        cr, uid, context = request.cr, request.uid, request.context
        transaction = request.registry['payment.transaction']

        reference = post.get('external_reference')
        if not reference:
            raise ValidationError(_("No local reference from MercadoPago"))

        tx_ids = transaction.search(cr, uid,
                                    [('reference', '=', reference)],
                                    context=context)
        if not tx_ids:
            raise ValidationError(
                _("No local transaction with reference %s") % reference)
        if len(tx_ids) > 1:
            raise ValidationError(
                _("Multiple transactions with reference %s") % reference)

        status = post.get('collection_status')
        if status not in ['approved', 'processed',
                          'pending', 'in_process', 'in_mediation',
                          'cancelled', 'refunded', 'charge_back', 'rejected']:
            raise ValidationError(
                _("Not valid status with reference %s") % reference)

        return transaction.form_feedback(
            cr,
            SUPERUSER_ID,
            post,
            'mercadopago',
            context=context)

    @http.route('/payment/mercadopago/ipn/', type='json', auth='none')
    def mercadopago_ipn(self, **post):
        """ MercadoPago IPN. """
        topic = request.httprequest.args.get('topic')
        tid = request.httprequest.args.get('id')

        _logger.info('Processing IPN: %s for %s' % (topic, tid))

        cr, context = request.cr, request.context
        acquirer = request.registry['payment.acquirer']

        if topic == 'merchant_order':
            # New order with transaction.
            tx, mo = acquirer.mercadopago_get_transaction_by_merchant_order(
                cr, SUPERUSER_ID, tid)
            if tx:
                _logger.info(
                    "MercadoPago: Confirm order %s for local order %s." %
                    (tid, tx.reference))
            else:
                # New order without transaction. Need create one!
                _logger.info("MercadoPago: New order %s." % tid)
        elif topic == 'payment':
            # Payment confirmation.
            tx, co = acquirer.mercadopago_get_transaction_by_collection(
                cr, SUPERUSER_ID, tid)
            if tx:
                _logger.info("MercadoPago: New payment to %s." % tid)
                tx.form_feedback(co[0], 'mercadopago')
            else:
                # New payment without transaction. Need create a payment!
                _logger.info("MercadoPago: New payment %s." % tid)
        else:
            _logger.info("MercadoPago: Unknown topic %s for %s."
                         % (topic, tid))

        return ''

    @http.route('/payment/mercadopago/dpn', type='http', auth="none")
    def mercadopago_dpn(self, **post):
        """ MercadoPago DPN """
        return_url = self._get_return_url(**post)
        self.mercadopago_validate_data(**post)
        return werkzeug.utils.redirect(return_url)

    @http.route('/payment/mercadopago/cancel', type='http', auth="none")
    def mercadopago_cancel(self, **post):
        """ When the user cancels its MercadoPago payment: GET on this route """
        _logger.info('Beginning MercadoPago cancel with post data %s',
                     pprint.pformat(post))  # debug
        return_url = self._get_return_url(**post)
        status = post.get('collection_status')
        if status == 'null':
            post['collection_status'] = 'cancelled'
        self.mercadopago_validate_data(**post)
        return werkzeug.utils.redirect(return_url)
