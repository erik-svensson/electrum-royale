import dataclasses
import functools
import re
from dataclasses import dataclass
from hashlib import sha256
from json.decoder import JSONDecodeError
from typing import List

import requests

from electrum.i18n import _
from electrum.logging import get_logger
from electrum.wallet import Abstract_Wallet

# todo set production address when it will be ready
API_CONNECTION_STRING = 'https://email-notifications.testnet.btcv.stage.rnd.land/api'
# timeout has to be smaller than resend cool down time
API_TIMEOUT = 25

_logger = get_logger(__name__)


@dataclass
class EmailNotificationWallet:
    name: str
    xpub: str
    derivation_path: str
    gap_limit: int
    address_range: str
    address_type: str
    recovery_public_key: str or None
    instant_public_key: str or None = None
    multisig_pubkeys: str or None = None

    def hash(self) -> str:
        hashing_string = self.address_type + self.xpub
        hashing_string += self.recovery_public_key if self.recovery_public_key else ''
        hashing_string += self.instant_public_key if self.instant_public_key else ''
        hashing_string += self.multisig_pubkeys if self.multisig_pubkeys else ''
        return sha256(hashing_string.encode('utf-8')).hexdigest()

    @classmethod
    def from_wallet(cls, wallet: Abstract_Wallet):
        multisig_pubkeys = None
        if re.match('[1-9]{1,2}of[1-9]{1,2}', wallet.wallet_type):
            multisig_pubkeys = f'{wallet.m},' + ','.join(k.xpub for k in wallet.get_keystores()[1:])
        return cls(
            name=str(wallet),
            xpub=wallet.get_keystore().xpub,
            derivation_path=wallet.keystore.get_derivation_prefix() if wallet.keystore.get_derivation_prefix() else 'm',
            gap_limit=wallet.gap_limit,
            address_range=f'{wallet.db.num_receiving_addresses()}/{wallet.db.num_change_addresses()}',
            address_type=wallet.txin_type,
            recovery_public_key=wallet.storage.get('recovery_pubkey', None),
            instant_public_key=wallet.storage.get('instant_pubkey', None),
            multisig_pubkeys=multisig_pubkeys,
        )

    @classmethod
    def is_subscribable(cls, wallet: Abstract_Wallet or None) -> bool:
        """Only wallets with xprv can be subscribed"""
        return bool(wallet and not wallet.is_watching_only())


class EmailNotificationApiError(Exception):
    def __init__(self, message: str,  http_status_code: int=0):
        super().__init__(message)
        self.http_status_code = http_status_code


class EmailAlreadySubscribedError(EmailNotificationApiError):
    pass


class TokenError(EmailNotificationApiError):
    pass


class NoMorePINAttemptsError(EmailNotificationApiError):
    pass


def mapping_errors(message: str, http_status_code: int) -> EmailNotificationApiError:
    email_already_subscribed_pattern = re.compile('Invalid wallet data: (.+) is already subscribed to (.+)')
    if http_status_code == 401 and message.startswith('Trials left'):
        n = re.findall('[0-9]+', message)[0]
        return EmailNotificationApiError(
            _('Please enter a valid code.') + '\n' +
            _('You have {number} more attempts.').format(number=n),
            http_status_code,
        )
    elif http_status_code == 429 and message.startswith('No more trials left'):
        return NoMorePINAttemptsError(
            _('You have entered an invalid code 3 times.') + '\n' +
            _('We have sent new code to your email address.'),
            http_status_code,
        )
    elif http_status_code == 408 and message.startswith('Request timeout'):
        return TokenError(
            _('This code is no longer active.') + '\n' +
            _('We have sent new code to your email address.'),
            http_status_code,
        )
    elif http_status_code == 400 and email_already_subscribed_pattern.match(message):
        email, wallet_name = email_already_subscribed_pattern.findall(message)[0]
        return EmailAlreadySubscribedError(
            _('{email} is already subscribed to {wallet_name}.').format(email=email, wallet_name=wallet_name),
            http_status_code,
        )
    return EmailNotificationApiError(
        _('Something went wrong.'),
        http_status_code,
    )


def request_error_handler(fun):
    @functools.wraps(fun)
    def wrapper(*args, **kwargs):
        try:
            response = fun(*args, **kwargs)
            # todo remove logger, only for debug purposes
            _logger.debug(f'Response from server {response.text} {response.status_code}')
            if response.status_code >= 400:
                _logger.info(f'Email api response error {response.text}')
                data = response.json()
                raise mapping_errors(
                    message=data.get('msg', '') if data.get('result', '') == 'error' else '',
                    http_status_code=response.status_code,
                )
            return response.json()
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout) as e:
            raise EmailNotificationApiError(_('Reached connection timeout.'))
        except requests.exceptions.ConnectionError as e:
            _logger.info(f'Email api connection error {str(e)}')
            raise EmailNotificationApiError(_('Something went wrong when connecting with server.'))
        except JSONDecodeError:
            raise EmailNotificationApiError(_('Something went wrong.'))
    return wrapper


class Connector:
    VERIFY = True

    def __init__(self, connection_string=API_CONNECTION_STRING, timeout=API_TIMEOUT):
        self.connection_string = connection_string
        self.timeout = timeout
        self.token = ''
        # todo remove it, only for debug purposes
        _logger.debug(f' Connection string {connection_string}')

    @classmethod
    def from_config(cls, config):
        kwargs = {}
        if config.get('email_server', ''):
            kwargs['connection_string'] = config.get('email_server')
        if config.get('email_server_timeout', 0):
            kwargs['timeout'] = config.get('email_server_timeout')
        return cls(**kwargs)

    @request_error_handler
    def subscribe_wallet(self, wallets: List[EmailNotificationWallet], email: str, language: str):
        # todo remove logger and payload, only for debug purposes
        payload_ = {
            'wallets': [dict(filter(lambda item: item[1] is not None, dataclasses.asdict(wallet).items())) for wallet in wallets],
            'email': email,
            'lang': language,
        }
        _logger.debug(f'SUB payload {payload_}')
        return requests.post(
            f'{self.connection_string}/subscribe/',
            json={
                'wallets': [dict(filter(lambda item: item[1] is not None, dataclasses.asdict(wallet).items())) for wallet in wallets],
                'email': email,
                'lang': language,
            },
            timeout=self.timeout,
            verify=self.VERIFY,
        )

    @request_error_handler
    def authenticate(self, pin: str):
        return requests.post(
            f'{self.connection_string}/authenticate/',
            json={
                'session_token': self.token,
                'pin': pin,
            },
            timeout=self.timeout,
            verify=self.VERIFY,
        )

    def set_token(self, response_json: dict):
        self.token = response_json['session_token']

    @request_error_handler
    def check_subscription(self, hashes: List[str], email: str):
        return requests.post(
            f'{self.connection_string}/check_subscription',
            json={
                'hashes': hashes,
                'email': email,
            },
            timeout=self.timeout,
            verify=self.VERIFY,
        )

    @request_error_handler
    def unsubscribe_wallet(self, wallet_hashes: List[str], email: str):
        return requests.post(
            f'{self.connection_string}/unsubscribe/',
            json={
                'hashes': wallet_hashes,
                'email': email,
            },
            timeout=self.timeout,
            verify=self.VERIFY,
        )

    @request_error_handler
    def modify_email(self, wallet_hashes: List[str], old_email: str, new_email: str):
        return requests.put(
            f'{self.connection_string}/modify/',
            json={
                'hashes': wallet_hashes,
                'old_email': old_email,
                'new_email': new_email,
            },
            timeout=self.timeout,
            verify=self.VERIFY,
        )

    @request_error_handler
    def resend(self):
        return requests.get(
            f'{self.connection_string}/resend/{self.token}/',
            timeout=self.timeout,
            verify=self.VERIFY,
        )
