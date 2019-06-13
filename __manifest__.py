# -*- coding: utf-8 -*-

{
    'name': 'MercadoPago Payment Acquirer',
    'category': 'Accounting',
    'summary': 'Payment Acquirer: MercadoPago Implementation for Odoo version 10.0',
    'version': '10.0',
    'description': """MercadoPago Payment Acquirer""",
    'author': 'Moldeo Interactive',
    'depends': ['payment', 'meli_oerp'],
    'data': [
        'views/mercadopago.xml',
        'views/payment_acquirer.xml',
        'views/res_config_view.xml',
        'data/mercadopago.xml',
    ],
    'installable': True,
}
