from enum import IntEnum

class PubkeyType(IntEnum):
    PUBKEY_ALERT = 0
    PUBKEY_INSTANT = 1
    PUBKEY_RECOVERY = 2
