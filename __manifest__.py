# -*- coding: utf-8 -*-

{
    'name': 'MercadoPago Payment Acquirer',
    'category': 'Accounting/Payment Acquirers',
    'sequence': 365,
    'summary': 'Payment Acquirer: MercadoPago Implementation',
    'version': '15.1.21.34',
    'description': """MercadoPago Payment Acquirer""",
    'author': 'Moldeo Interactive',
    'website': 'https://www.moldeointeractive.com',
    'depends': ['payment','website','website_sale'],
    'data': [
        'views/mercadopago.xml',
        'views/payment_acquirer.xml',
        #'views/res_config_view.xml',
        'data/mercadopago.xml',
    ],
    'images': ['src/img/mercadopago_icon.png','src/img/mercadopago_logo.png',
                'src/img/mercadopago_logo_64.png',
                'static/description/payment_mercadopago_screenshot.png','static/description/main_screenshot.png',
                'static/description/main2_screenshot.png',
                'static/description/create_application_mp_sreenshot.png','static/description/credentials_mercadopago_screenshot.png'],
    'installable': True,
    'application': True,
    'license': 'GPL-3',
    #'post_init_hook': 'create_missing_journal_for_acquirers',
}
