# -*- coding: utf-8 -*-

{
    'name': 'MercadoPago Payment Acquirer',
    'category': 'Hidden',
    'summary': 'Payment Acquirer: MercadoPago Implementation',
    'version': '9.0.0.0.0',
    'description': """MercadoPago Payment Acquirer""",
    'author': 'Moldeo Interactive - www.moldeo.coop',
    'depends': ['payment'],
    'data': [
        'views/mercadopago.xml',
        'views/payment_acquirer.xml',
        'views/res_config_view.xml',
        'data/mercadopago.xml',
    ],
    'test': [
    ],
    'installable': True,
}
