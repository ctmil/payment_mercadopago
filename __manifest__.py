# -*- coding: utf-8 -*-

{
    'name': 'MercadoPago Payment Acquirer',
    'category': 'Accounting',
    'summary': 'Payment Acquirer: MercadoPago Implementation',
    'version': '1.0',
    'description': """MercadoPago Payment Acquirer""",
    'author': 'Moldeo Interactive',
    'depends': ['payment'],
    'data': [
        'views/mercadopago.xml',
        'views/payment_acquirer.xml',
        #'views/res_config_view.xml',
        'data/mercadopago.xml',
    ],
    'installable': True,
    'post_init_hook': 'create_missing_journal_for_acquirers',
}
