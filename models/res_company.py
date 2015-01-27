# -*- coding: utf-8 -*-

from openerp.osv import fields, osv


class ResCompany(osv.Model):
    _inherit = "res.company"

    def _get_mercadopago_account(self, cr, uid, ids, name, arg, context=None):
        Acquirer = self.pool['payment.acquirer']
        company_id = self.pool['res.users'].browse(cr, uid, uid, context=context).company_id.id
        
        mercadopago_ids = Acquirer.search(cr, uid, [
            ('website_published', '=', True),
            ('name', 'ilike', 'mercadopago'),
            ('company_id', '=', company_id),
        ], limit=1, context=context)
        if mercadopago_ids:
            MP = Acquirer.browse(cr, uid, mercadopago_ids[0], context=context)
            return dict.fromkeys(ids, MP.mercadopago_email_account)
        return dict.fromkeys(ids, False)

    def _set_mercadopago_account(self, cr, uid, id, name, value, arg, context=None):
        Acquirer = self.pool['payment.acquirer']
        company_id = self.pool['res.users'].browse(cr, uid, uid, context=context).company_id.id
        mercadopago_account = self.browse(cr, uid, id, context=context).mercadopago_account
        mercadopago_ids = Acquirer.search(cr, uid, [
            ('website_published', '=', True),
            ('mercadopago_email_account', '=', mercadopago_account),
            ('company_id', '=', company_id),
        ], context=context)
        if mercadopago_ids:
            Acquirer.write(cr, uid, mercadopago_ids, {'mercadopago_email_account': value}, context=context)
        return True

    _columns = {
        'mercadopago_account': fields.function(
            _get_mercadopago_account,
            fnct_inv=_set_mercadopago_account,
            nodrop=True,
            type='char', string='MercadoPago Account',
            help="MercadoPago username (usually email) for receiving online payments."
        ),
    }
