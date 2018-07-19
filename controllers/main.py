# -*- coding: utf-8 -*-

try:
    import simplejson as json
except ImportError:
    import json
import logging
import pprint
import urllib2
import werkzeug

from odoo import http, SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)


class MercadoPagoController(http.Controller):
    _notify_url = '/payment/mercadopago/ipn/'
    _return_url = '/payment/mercadopago/dpn/'
    _cancel_url = '/payment/mercadopago/cancel/'

    def _get_return_url(self, **post):
        """ Extract the return URL from the data coming from MercadoPago. """

#        return_url = post.pop('return_url', '')
#        if not return_url:
#            custom = json.loads(post.pop('custom', False) or '{}')
#            return_url = custom.get('return_url', '/')
        return_url = ''
        return return_url

    def mercadopago_validate_data(self, **post):
        """ MercadoPago IPN: three steps validation to ensure data correctness

         - step 1: return an empty HTTP 200 response -> will be done at the end
           by returning ''
         - step 2: POST the complete, unaltered message back to MercadoPago (preceded
           by cmd=_notify-validate), with same encoding
         - step 3: mercadopago send either VERIFIED or INVALID (single word)

        Once data is validated, process it. """
        res = False
        #new_post = dict(post, cmd='_notify-validate')

#       topic = payment
#       id = identificador-de-la-operación
        topic = post.get('topic')
        op_id = post.get('id')

        cr, uid, context = request.cr, request.uid, request.context
        reference = post.get('external_reference')
        tx = None
        if reference:
            tx = request.env['payment.transaction'].search( [('reference', '=', reference)])
            _logger.info('mercadopago_validate_data() > payment.transaction: %s' % tx)


        _logger.info('MercadoPago: validating data')
        #print "new_post:", new_post
        _logger.info('MercadoPago: %s' % post)


        if tx:
            _logger.info('MercadoPago: ')
            res = request.env['payment.transaction'].sudo().form_feedback( post, 'mercadopago')

#        https://api.mercadolibre.com/collections/?access_token=
#        if :

#        mercadopago_urls = request.registry['payment.acquirer']._get_mercadopago_urls(cr, uid, tx and tx.acquirer_id and tx.acquirer_id.env or 'prod', context=context)
#        validate_url = mercadopago_urls['mercadopago_form_url']
#        urequest = urllib2.Request(validate_url, werkzeug.url_encode(new_post))
#        uopen = urllib2.urlopen(urequest)
#        resp = uopen.read()
#        if resp == 'VERIFIED':
#            _logger.info('MercadoPago: validated data')
#            res = request.registry['payment.transaction'].form_feedback(cr, SUPERUSER_ID, post, 'mercadopago', context=context)
#        elif resp == 'INVALID':
#            _logger.warning('MercadoPago: answered INVALID on data verification')
#        else:
#            _logger.warning('MercadoPago: unrecognized mercadopago answer, received %s instead of VERIFIED or INVALID' % resp.text)
        return res

    @http.route('/payment/mercadopago/ipn/', type='http', auth='none')
    def mercadopago_ipn(self, **post):
        """ MercadoPago IPN. """
        # recibimo algo como http://www.yoursite.com/notifications?topic=payment&id=identificador-de-la-operación
        #segun el topic:
        # luego se consulta con el "id"
        _logger.info('Beginning MercadoPago IPN form_feedback with post data %s', pprint.pformat(post))  # debug
        self.mercadopago_validate_data(**post)
        return ''

    @http.route('/payment/mercadopago/dpn', type='http', auth="none")
    def mercadopago_dpn(self, **post):
        """ MercadoPago DPN """
        _logger.info('Beginning MercadoPago DPN form_feedback with post data %s', pprint.pformat(post))  # debug
        return_url = self._get_return_url(**post)
        self.mercadopago_validate_data(**post)
        return werkzeug.utils.redirect(return_url)

    @http.route('/payment/mercadopago/cancel', type='http', auth="none")
    def mercadopago_cancel(self, **post):
        #import pdb; pdb.set_trace()
        """ When the user cancels its MercadoPago payment: GET on this route """
        cr, uid, context = request.cr, SUPERUSER_ID, request.context
        _logger.info('Beginning MercadoPago cancel with post data %s', pprint.pformat(post))  # debug
        return_url = self._get_return_url(**post)
        status = post.get('collection_status')
        if status=='null':
            post['collection_status'] = 'cancelled'
        self.mercadopago_validate_data(**post)
        return werkzeug.utils.redirect(return_url)
