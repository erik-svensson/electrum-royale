import dataclasses
import functools
import json
import os
from dataclasses import dataclass
from hashlib import sha256
from json.decoder import JSONDecodeError
from typing import List

import requests

from electrum.logging import get_logger

HOST = os.environ.get('EMAIL_API_HOST', 'https://localhost')
PORT = os.environ.get('EMAIL_API_PORT', '4000')
TIMEOUT = os.environ.get('EMAIL_API_TIMEOUT', '4')

_logger = get_logger(__name__)


@dataclass
class EmailApiWallet:
    name: str
    xpub: str
    derivation_path: List[str]
    gap_limit: int
    recovery_public_key: str
    instant_public_key: str or None

    def hash(self) -> str:
        return sha256(json.dumps({
            'xpub': self.xpub,
            'derivation_path': self.derivation_path,
            'recovery_public_key': self.recovery_public_key,
            'instant_public_key': self.instant_public_key,
        }, separators=(',', ':')).encode('utf-8')).hexdigest()

    @classmethod
    def from_wallet(cls, wallet):
        recovery_public_key = wallet.storage.get('recovery_pubkey', None)
        instant_public_key = wallet.storage.get('instant_pubkey', '')
        return cls(
            name=str(wallet),
            xpub=wallet.keystore.xpub,
            # todo: find derivation path for change address
            derivation_path=[wallet.keystore._derivation_prefix, 'change addresses derivation prefix'],
            gap_limit=wallet.gap_limit,
            # sometimes we get keys in tuple, need for refactoring
            recovery_public_key=recovery_public_key[0] if isinstance(recovery_public_key, tuple) else recovery_public_key,
            instant_public_key=instant_public_key[0] if isinstance(instant_public_key, tuple) else instant_public_key,
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
                if data.get('result', None) == 'error':
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

    def __init__(self, host=HOST, port=int(PORT), timeout=int(TIMEOUT)):
        self.connection_string = f'{host}:{port}'
        self.timeout = timeout
        self.token = ''

    @request_error_handler
    def subscribe_email(self, wallets: List[EmailApiWallet], email: str, language: str):
        return requests.post(
            f'{self.connection_string}/subscribe',
            json={
                'wallets': [dataclasses.asdict(wallet) for wallet in wallets],
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
