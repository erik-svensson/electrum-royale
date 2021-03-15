from electrum.notification_connector import EmailNotificationWallet
from electrum.wallet import Abstract_Wallet


class EmailNotificationConfig:
    CONFIG_KEY = 'email_notifications'

    @staticmethod
    def _to_email_api_wallet(wallet):
        if isinstance(wallet, Abstract_Wallet):
            wallet = EmailNotificationWallet.from_wallet(wallet)
        return wallet

    @staticmethod
    def check_if_wallet_in_config(config, wallet):
        wallet = EmailNotificationConfig._to_email_api_wallet(wallet)
        data = config.get(EmailNotificationConfig.CONFIG_KEY, {})
        return wallet.hash() in data

    @staticmethod
    def get_wallet_email(config, wallet):
        if not EmailNotificationConfig.check_if_wallet_in_config(config, wallet):
            return ''
        wallet = EmailNotificationConfig._to_email_api_wallet(wallet)
        return config.get(EmailNotificationConfig.CONFIG_KEY)[wallet.hash()]

    @staticmethod
    def save_email_to_config(config, wallet, email):
        wallet = EmailNotificationConfig._to_email_api_wallet(wallet)
        data = config.get(EmailNotificationConfig.CONFIG_KEY, {})
        data[wallet.hash()] = email
        config.set_key(EmailNotificationConfig.CONFIG_KEY, data)
