from typing import List

from .multikey_generator import MultiKeyScriptGenerator
from ..bitcoin import opcodes, push_script


class ThreeKeysError(Exception):
    pass


class TwoKeysScriptGenerator(MultiKeyScriptGenerator):
    def __init__(self, recovery_pubkey: str):
        self.recovery_pubkey = recovery_pubkey
        self._recovery_alert_flag = None
        self.witness_flags = []

    @staticmethod
    def create_redeem_script(alert_pubkey, recovery_pubkey):
        return (
                opcodes.OP_IF.hex() +
                opcodes.OP_1.hex() +
                opcodes.OP_ELSE.hex() +
                opcodes.OP_2.hex() +
                opcodes.OP_ENDIF.hex() +
                push_script(alert_pubkey) +
                push_script(recovery_pubkey) +
                opcodes.OP_2.hex() +
                opcodes.OP_CHECKMULTISIG.hex()
        )

    @staticmethod
    def _create_script_sig(signatures, flag, redeem_script):
        return (
                opcodes.OP_0.hex() +
                signatures +
                flag +
                push_script(redeem_script)
        )

    def get_redeem_script(self, public_keys: List[str]) -> str:
        if not isinstance(public_keys, list) or len(public_keys) not in [1, 2]:
            raise ThreeKeysError(f"Wrong input type! Expected 1 or 2 elements list not '{public_keys}'")
        # filter out recovery pubkey
        filtered_keys = list(filter(lambda item: item != self.recovery_pubkey, public_keys))
        if len(filtered_keys) != 1:
            raise ThreeKeysError(f'Cannot deduce pubkey from {public_keys}')

        pub_key = filtered_keys[0]
        return self.create_redeem_script(pub_key, self.recovery_pubkey)

    def get_script_sig(self, signatures: List[str], public_keys: List[str]) -> str:
        if self._recovery_alert_flag is None:
            raise ThreeKeysError('Recovery/alert flag not set!')
        sigs = ''.join(push_script(sig) for sig in signatures)
        return self._create_script_sig(sigs, self._recovery_alert_flag, self.get_redeem_script(public_keys))

    def set_alert(self):
        # 1 of 2
        self._recovery_alert_flag = opcodes.OP_1.hex()
        self.witness_flags = [1]

    def set_recovery(self):
        # 2 of 2
        self._recovery_alert_flag = opcodes.OP_0.hex()
        self.witness_flags = [0]

    def is_recovery_mode(self):
        return self.witness_flags == [0]

    def is_alert_mode(self):
        return self.witness_flags == [1]


class ThreeKeysScriptGenerator(MultiKeyScriptGenerator):
    def __init__(self, recovery_pubkey: str, instant_pubkey: str):
        self.recovery_pubkey = recovery_pubkey
        self.instant_pubkey = instant_pubkey
        self._instant_recovery_alert_flag = None
        self.witness_flags = []

    @staticmethod
    def create_redeem_script(alert_pubkey, instant_pubkey, recovery_pubkey):
        return (
                opcodes.OP_IF.hex() +
                opcodes.OP_1.hex() +
                opcodes.OP_ELSE.hex() +
                opcodes.OP_IF.hex() +
                opcodes.OP_2.hex() +
                opcodes.OP_ELSE.hex() +
                opcodes.OP_3.hex() +
                opcodes.OP_ENDIF.hex() +
                opcodes.OP_ENDIF.hex() +
                push_script(alert_pubkey) +
                push_script(instant_pubkey) +
                push_script(recovery_pubkey) +
                opcodes.OP_3.hex() +
                opcodes.OP_CHECKMULTISIG.hex()
        )

    @staticmethod
    def _create_script_sig(signatures, flags, redeem_script):
        return (
                opcodes.OP_0.hex() +
                signatures +
                flags +
                push_script(redeem_script)
        )

    def get_redeem_script(self, public_keys: List[str]) -> str:
        if not isinstance(public_keys, list) or len(public_keys) > 3:
            raise ThreeKeysError(f"Wrong input type! Expected list not '{public_keys}'")

        pub_key = public_keys[0]
        return self.create_redeem_script(pub_key, self.instant_pubkey, self.recovery_pubkey)

    def get_script_sig(self, signatures: List[str], public_keys: List[str]) -> str:
        if self._instant_recovery_alert_flag is None:
            raise ThreeKeysError('Recovery/alert/instant flag not set!')
        sigs = ''.join(push_script(sig) for sig in signatures)
        return self._create_script_sig(sigs, self._instant_recovery_alert_flag, self.get_redeem_script(public_keys))

    def set_alert(self):
        # 1 of 3
        self._instant_recovery_alert_flag = opcodes.OP_1.hex()
        self.witness_flags = [1]

    def set_recovery(self):
        # 3 of 3
        self._instant_recovery_alert_flag = opcodes.OP_0.hex() + opcodes.OP_0.hex()
        self.witness_flags = [0, 0]

    def set_instant(self):
        # 2 of 3
        self._instant_recovery_alert_flag = opcodes.OP_1.hex() + opcodes.OP_0.hex()
        self.witness_flags = [1, 0]

    def is_recovery_mode(self):
        return self.witness_flags == [0, 0]

    def is_instant_mode(self):
        return self.witness_flags == [1, 0]

    def is_alert_mode(self):
        return self.witness_flags == [1]


class TwoKeysHWScriptGenerator(TwoKeysScriptGenerator):
    def __init__(self, recovery_pubkey: str):
        self._recovery_alert_flag = None
        self.recovery_pubkey = recovery_pubkey
        self.witness_flags = []

    def get_redeem_script(self, public_keys: List[str]) -> str:
        if not isinstance(public_keys, list) or len(public_keys) != 2:
            raise ThreeKeysError(f"Wrong input type! Expected 2 elements list not '{public_keys}'")
        return self.create_redeem_script(public_keys[0], public_keys[1])


class ThreeKeysHWScriptGenerator(ThreeKeysScriptGenerator):
    def __init__(self):
        self._instant_recovery_alert_flag = None
        self.witness_flags = []

    def get_redeem_script(self, public_keys: List[str]) -> str:
        if not isinstance(public_keys, list) or len(public_keys) != 3:
            raise ThreeKeysError(f"Wrong input type! Expected 3 elements list not '{public_keys}'")
        return self.create_redeem_script(public_keys[0], public_keys[1], public_keys[2])
