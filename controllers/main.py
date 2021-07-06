# -*- coding: utf-8 -*-

try:
    import simplejson as json
except ImportError:
    import json
import logging
import pprint

try:
    #python2
    import urlparse as parse
except ImportError:
    #python3
    from urllib import parse

import werkzeug

from odoo import http, SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)


class MercadoPagoController(http.Controller):
    _notify_url = '/payment/mercadopago/ipn/'
    _return_url = '/payment/mercadopago/dpn/'
    _cancel_url = '/payment/mercadopago/cancel/'

    def mercadopago_validate_data(self, **post):
        """ MercadoPago IPN: three steps validation to ensure data correctness

         - step 1: return an empty HTTP 200 response -> will be done at the end
           by returning ''
         - step 2: POST the complete, unaltered message back to MercadoPago (preceded
           by cmd=_notify-validate), with same encoding
         - step 3: mercadopago send either VERIFIED or INVALID (single word)

        Once data is validated, process it. """
        res = False

#       topic = payment
#       id = identificador-de-la-operación
        topic = post.get('topic')
        op_id = post.get('id')

        reference = post.get('external_reference')

        if not reference and (topic and str(topic) in ["payment", "merchant_order"] and op_id):
            _logger.info('MercadoPago Topic: %s. payment ID: %s', str(topic), str(op_id))
            reference = request.env["payment.acquirer"].sudo().mercadopago_get_reference(payment_id=op_id, topic=topic)

        tx = None
        if reference:
            tx = request.env['payment.transaction'].sudo().search([('reference', '=', reference)])
            _logger.info('mercadopago_validate_data() > payment.transaction founded: %s' % tx.reference)

        _logger.info('MercadoPago: validating data')
        #print "new_post:", new_post
        _logger.info('MercadoPago Post: %s' % post)

        if (tx):
            post.update({'external_reference': reference})
            _logger.info('MercadoPago Post Updated: %s' % post)
            res = request.env['payment.transaction'].sudo().form_feedback(post, 'mercadopago')
        return res

    @http.route('/payment/mercadopago/ipn/', type='json', auth='none')
    def mercadopago_ipn(self, **post):
        """ MercadoPago IPN. """
        # recibimo algo como http://www.yoursite.com/notifications?topic=payment&id=identificador-de-la-operación
        #segun el topic: # luego se consulta con el "id"
        _logger.info('Beginning MercadoPago IPN form_feedback with post data %s', pprint.pformat(post))  # debug
        querys = parse.urlsplit(request.httprequest.url).query
        params = dict(parse.parse_qsl(querys))
        if params and ('topic' in params or 'type' in params) and ('id' in params or 'data.id' in params):
            self.mercadopago_validate_data(**params)
        else:
            self.mercadopago_validate_data(**post)
        return werkzeug.wrappers.Response(status=200)

    @http.route('/payment/mercadopago/dpn', type='http', auth="none")
    def mercadopago_dpn(self, **post):
        """ MercadoPago DPN """
        _logger.info('Beginning MercadoPago DPN form_feedback with post data %s', pprint.pformat(post))  # debug
        self.mercadopago_validate_data(**post)
        return werkzeug.utils.redirect('/payment/process')

    @http.route('/payment/mercadopago/cancel', type='http', auth="none")
    def mercadopago_cancel(self, **post):
        """ When the user cancels its MercadoPago payment: GET on this route """
        _logger.info('Beginning MercadoPago cancel with post data %s', pprint.pformat(post))  # debug
        status = post.get('collection_status')
        if status == 'null':
            post['collection_status'] = 'cancelled'
        self.mercadopago_validate_data(**post)
        return werkzeug.utils.redirect('/payment/process')
