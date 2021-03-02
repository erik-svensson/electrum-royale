import dataclasses
import functools
from dataclasses import dataclass
from hashlib import sha256
from json.decoder import JSONDecodeError
from typing import List

import requests

from electrum.interface import deserialize_server
from electrum.logging import get_logger


HOST = 'https://btcv-notifcations-email.rnd.land/api'
PORT = 443
TIMEOUT = 20

_logger = get_logger(__name__)


def extract_server(server: str):
    host, port, _ = deserialize_server(str(server) + ':s')
    return host, port


@dataclass
class EmailApiWallet:
    name: str
    xpub: str
    derivation_path: List[str]
    gap_limit: int
    address_range: str
    address_type: str
    recovery_public_key: str or None
    instant_public_key: str or None = None

    def hash(self) -> str:
        hashing_string = self.address_type + self.xpub
        hashing_string += self.recovery_public_key if self.recovery_public_key else ''
        hashing_string += self.instant_public_key if self.instant_public_key else ''
        return sha256(hashing_string.encode('utf-8')).hexdigest()

    @classmethod
    def from_wallet(cls, wallet):
        return cls(
            name=str(wallet),
            xpub=wallet.keystore.xpub,
            derivation_path=wallet.keystore._derivation_prefix if wallet.keystore._derivation_prefix else 'm',
            gap_limit=wallet.gap_limit,
            address_range=f'{wallet.db.num_receiving_addresses()}/{wallet.db.num_change_addresses()}',
            address_type=wallet.txin_type,
            recovery_public_key=wallet.storage.get('recovery_pubkey', None),
            instant_public_key=wallet.storage.get('instant_pubkey', None),
        )


class ApiError(Exception):
    pass


def request_error_handler(fun):
    @functools.wraps(fun)
    def wrapper(*args, **kwargs):
        try:
            response = fun(*args, **kwargs)
            if response.status_code != 200:
                data = response.json()
                if data.get('result', '') == 'error':
                    raise ApiError(f"<b>ERROR</b> {data.get('msg')}")
                raise ApiError('Something went wrong')
            return response.json()
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout) as e:
            raise ApiError(f'<b>ERROR</b> Reached connection timeout')
        except requests.exceptions.ConnectionError as e:
            _logger.info(f'Email api connection error {str(e)}')
            raise ApiError(f'<b>ERROR</b> Something went wrong when connecting with server')
        except JSONDecodeError:
            raise ApiError('Something went wrong')
    return wrapper


class Connector:
    # todo: This is mock for self-signed certificate verification
    VERIFY = False

    def __init__(self, host=HOST, port=PORT, timeout=TIMEOUT):
        self.connection_string = f'{host}:{port}'
        self.timeout = timeout
        self.token = ''

    @request_error_handler
    def subscribe_email(self, wallets: List[EmailApiWallet], email: str, language: str):
        return requests.post(
            f'{self.connection_string}/subscribe',
            json={
                'wallets': [dict(filter(lambda item: item[1] is not None, dataclasses.asdict(wallet).items())) for wallet in wallets],
                'email': email,
                'lang': language,
            },
            timeout=self.timeout,
            verify=self.VERIFY,
        )

    @request_error_handler
    def authenticate(self, pin: int):
        return requests.post(
            f'{self.connection_string}/authenticate',
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
        return requests.get(
            f'{self.connection_string}/check_subscription',
            json={
                'hashes': hashes,
                'email': email,
            },
            timeout=self.timeout,
            verify=self.VERIFY,
        )
