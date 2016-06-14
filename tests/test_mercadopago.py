# -*- coding: utf-8 -*-

from openerp.addons.payment.models.payment_acquirer import ValidationError
from openerp.addons.payment.tests.common import PaymentAcquirerCommon
from openerp.addons.payment_mercadopago.controllers.main \
    import MercadoPagoController
from openerp.tools import mute_logger

from lxml import objectify
import urlparse


class MercadoPagoCommon(PaymentAcquirerCommon):

    def setUp(self):
        super(MercadoPagoCommon, self).setUp()
        cr, uid = self.cr, self.uid
        self.base_url = self.registry('ir.config_parameter').get_param(
            cr, uid, 'web.base.url')

        # get the mercadopago account
        model, self.mercadopago_id = self.registry('ir.model.data')\
            .get_object_reference(cr, uid,
                                  'payment_mercadopago',
                                  'payment_acquirer_mercadopago')

        self.payment_acquirer \
            .write(self.cr, self.uid, self.mercadopago_id, {
                'mercadopago_client_id': '6998660949904288',
                'mercadopago_secret_key': 'l4jtD08NVv9nPcrFi9T6NvlO1MFPEU2O',
            })

        # tde+seller@openerp.com -
        # tde+buyer@openerp.com -
        # tde+buyer-it@openerp.com

        # some CC
        self.amex = (('378282246310005', '123'),
                     ('371449635398431', '123'))
        self.amex_corporate = (('378734493671000', '123'))
        self.autralian_bankcard = (('5610591081018250', '123'))
        self.dinersclub = (('30569309025904', '123'),
                           ('38520000023237', '123'))
        self.discover = (('6011111111111117', '123'),
                         ('6011000990139424', '123'))
        self.jcb = (('3530111333300000', '123'),
                    ('3566002020360505', '123'))
        self.mastercard = (('5555555555554444', '123'),
                           ('5105105105105100', '123'))
        self.visa = (('4111111111111111', '123'),
                     ('4012888888881881', '123'),
                     ('4222222222222', '123'))
        self.dankord_pbs = (('76009244561', '123'),
                            ('5019717010103742', '123'))
        self.switch_polo = (('6331101999990016', '123'))

        # Set ARS
        model, self.currency_ars_id = self.registry('ir.model.data') \
            .get_object_reference(cr, uid, 'base', 'ARS')
        self.currency_ars = self.registry('res.currency') \
            .browse(cr, uid, self.currency_ars_id)


class MercadoPagoServer2Server(MercadoPagoCommon):

    def test_00_tx_management(self):
        cr, uid, context = self.cr, self.uid, {}
        # be sure not to do stupid things
        mercadopago = self.payment_acquirer \
            .browse(self.cr, self.uid, self.mercadopago_id, None)
        self.assertEqual(mercadopago.environment,
                         'test',
                         'test without test environment')

        res = self.payment_acquirer._mercadopago_s2s_get_access_token(
            cr, uid, [self.mercadopago_id], context=context)
        self.assertTrue(res[self.mercadopago_id] is not False,
                        'mercadopago: did not generate access token')

        tx_id = self.payment_transaction.s2s_create(
            cr, uid, {
                'amount': 0.01,
                'acquirer_id': self.mercadopago_id,
                'currency_id': self.currency_ars_id,
                'reference': 'test_reference',
                'partner_id': self.buyer_id,
            }, {
                'number': self.visa[0][0],
                'cvc': self.visa[0][1],
                'brand': 'visa',
                'expiry_mm': 9,
                'expiry_yy': 2015,
            }, context=context
        )

        tx = self.payment_transaction.browse(cr, uid, tx_id, context=context)
        self.assertTrue(tx.mercadopago_txn_id is not False,
                        'mercadopago:'
                        ' txn_id should have been set after s2s request')

        self.payment_transaction.write(cr, uid, tx_id,
                                       {'mercadopago_txn_id': False},
                                       context=context)


class MercadoPagoForm(MercadoPagoCommon):

    def test_10_mercadopago_form_render(self):
        cr, uid, context = self.cr, self.uid, {}
        # be sure not to do stupid things
        self.payment_acquirer.write(
            cr, uid,
            self.mercadopago_id, {'fees_active': False}, context)

        mercadopago = self.payment_acquirer.browse(cr, uid,
                                                   self.mercadopago_id, context)
        self.assertEqual(mercadopago.environment,
                         'test',
                         'test without test environment')

        # ----------------------------------------
        # Test: button direct rendering
        # ----------------------------------------

        # render the button
        res = self.payment_acquirer.render(
            cr, uid, self.mercadopago_id,
            'test_ref0', 0.01, self.currency_ars_id,
            partner_id=None,
            values=self.buyer_values,
            context=context)

        form_values = {
            'cmd': '_xclick',
            'business': 'tde+mercadopago-facilitator@openerp.com',
            'item_name': 'test_ref0',
            'item_number': 'test_ref0',
            'first_name': 'Buyer',
            'last_name': 'Norbert',
            'amount': '0.01',
            'currency_code': 'ARS',
            'address1': 'Huge Street 2/543',
            'city': 'Sin City',
            'zip': '1000',
            'country': 'Argentina',
            'email': 'norbert.buyer@example.com',
            'return': '%s' % urlparse.urljoin(
                self.base_url, MercadoPagoController._return_url),
            'notify_url': '%s' % urlparse.urljoin(
                self.base_url, MercadoPagoController._notify_url),
            'cancel_return': '%s' % urlparse.urljoin(
                self.base_url, MercadoPagoController._cancel_url),
        }

        # check Button result
        tree = objectify.fromstring(res)
        self.assertEqual(
            tree.get('href').split('?')[0],
            'https://sandbox.mercadopago.com/mla/checkout/pay',
            'mercadopago: wrong url')

    def test_11_mercadopago_form_with_fees(self):

        cr, uid, context = self.cr, self.uid, {}
        # be sure not to do stupid things
        mercadopago = self.payment_acquirer.browse(
            self.cr, self.uid, self.mercadopago_id, None)
        self.assertEqual(
            mercadopago.environment, 'test', 'test without test environment')

        # update acquirer: compute fees
        self.payment_acquirer.write(cr, uid, self.mercadopago_id, {
            'fees_active': True,
            'fees_dom_fixed': 1.0,
            'fees_dom_var': 0.35,
            'fees_int_fixed': 1.5,
            'fees_int_var': 0.50,
        }, context)

        # render the button
        res = self.payment_acquirer.render(
            cr, uid, self.mercadopago_id,
            'test_ref0', 12.50, self.currency_euro,
            partner_id=None,
            partner_values=self.buyer_values,
            context=context)

        # check form result
        handling_found = False
        tree = objectify.fromstring(res)
        self.assertEqual(tree.get('action'),
                         'https://www.sandbox.mercadopago.com/cgi-bin/webscr',
                         'mercadopago: wrong form POST url')
        for form_input in tree.input:
            if form_input.get('name') in ['handling']:
                handling_found = True
                self.assertEqual(
                    form_input.get('value'),
                    '1.57', 'mercadopago: wrong computed fees')
        self.assertTrue(
            handling_found,
            'mercadopago:'
            ' fees_active did not add handling input in rendered form')

    @mute_logger('openerp.addons.payment_mercadopago.models.mercadopago',
                 'ValidationError')
    def test_20_mercadopago_form_management(self):
        cr, uid, context = self.cr, self.uid, {}
        # be sure not to do stupid things
        mercadopago = self.payment_acquirer.browse(cr, uid,
                                                   self.mercadopago_id, context)
        self.assertEqual(mercadopago.environment,
                         'test',
                         'test without test environment')

        # typical data posted by mercadopago after client has successfully paid
        mercadopago_post_data = {
            'protection_eligibility': u'Ineligible',
            'last_name': u'Poilu',
            'txn_id': u'08D73520KX778924N',
            'receiver_email': u'tde+mercadopago-facilitator@openerp.com',
            'payment_status': u'Pending',
            'payment_gross': u'',
            'tax': u'0.00',
            'residence_country': u'FR',
            'address_state': u'Alsace',
            'payer_status': u'verified',
            'txn_type': u'web_accept',
            'address_street': u'Av. de la Pelouse, 87648672 Mayet',
            'handling_amount': u'0.00',
            'payment_date': u'03:21:19 Nov 18, 2013 PST',
            'first_name': u'Norbert',
            'item_name': u'test_ref_2',
            'address_country': u'France',
            'charset': u'windows-1252',
            'custom': u'',
            'notify_version': u'3.7',
            'address_name': u'Norbert Poilu',
            'pending_reason': u'multi_currency',
            'item_number': u'test_ref_2',
            'receiver_id': u'DEG7Z7MYGT6QA',
            'transaction_subject': u'',
            'business': u'tde+mercadopago-facilitator@openerp.com',
            'test_ipn': u'1',
            'payer_id': u'VTDKRZQSAHYPS',
            'verify_sign':
            u'An5ns1Kso7MWUdW4ErQKJJJ4qi4-AVoiUf-3478q3vrSmqh08IouiYpM',
            'address_zip': u'75002',
            'address_country_code': u'FR',
            'address_city': u'Paris',
            'address_status': u'unconfirmed',
            'mc_currency': u'EUR',
            'shipping': u'0.00',
            'payer_email': u'tde+buyer@openerp.com',
            'payment_type': u'instant',
            'mc_gross': u'1.95',
            'ipn_track_id': u'866df2ccd444b',
            'quantity': u'1'
        }

        # should raise error about unknown tx
        with self.assertRaises(ValidationError):
            self.payment_transaction.form_feedback(
                cr, uid, mercadopago_post_data, 'mercadopago', context=context)

        # create tx
        tx_id = self.payment_transaction.create(
            cr, uid, {
                'amount': 1.95,
                'acquirer_id': self.mercadopago_id,
                'currency_id': self.currency_euro_id,
                'reference': 'test_ref_2',
                'partner_name': 'Norbert Buyer',
                'partner_country_id': self.country_france_id,
            }, context=context
        )
        # validate it
        self.payment_transaction.form_feedback(
            cr, uid, mercadopago_post_data, 'mercadopago', context=context)
        # check
        tx = self.payment_transaction.browse(cr, uid, tx_id, context=context)
        self.assertEqual(
            tx.state,
            'pending',
            'mercadopago:'
            ' wrong state after receiving a valid pending notification')
        self.assertEqual(
            tx.state_message,
            'multi_currency',
            'mercadopago:'
            ' wrong state message after receiving a valid pending notification')
        self.assertEqual(
            tx.mercadopago_txn_id,
            '08D73520KX778924N',
            'mercadopago:'
            ' wrong txn_id after receiving a valid pending notification')
        self.assertFalse(
            tx.date_validate,
            'mercadopago:'
            ' validation date should not be updated when receiving'
            ' pending notification')

        # update tx
        self.payment_transaction.write(cr, uid, [tx_id], {
            'state': 'draft',
            'mercadopago_txn_id': False,
        }, context=context)
        # update notification from mercadopago
        mercadopago_post_data['payment_status'] = 'Completed'
        # validate it
        self.payment_transaction.form_feedback(
            cr, uid,
            mercadopago_post_data, 'mercadopago', context=context)
        # check
        tx = self.payment_transaction.browse(cr, uid, tx_id, context=context)
        self.assertEqual(
            tx.state,
            'done',
            'mercadopago:'
            ' wrong state after receiving a valid pending notification')
        self.assertEqual(
            tx.mercadopago_txn_id,
            '08D73520KX778924N',
            'mercadopago:'
            ' wrong txn_id after receiving a valid pending notification')
        self.assertEqual(
            tx.date_validate,
            '2013-11-18 03:21:19',
            'mercadopago: wrong validation date')
