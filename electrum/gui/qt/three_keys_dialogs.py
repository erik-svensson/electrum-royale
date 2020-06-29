from enum import IntEnum

from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QVBoxLayout, QToolTip, QTextEdit

from electrum.ecc import ECPubkey


class ValidationState(IntEnum):
    INVALID = 0
    VALID = 1
    INTERMEDIATE = 2


class PubKeyValidator:
    def __init__(self, text_edit: QTextEdit, tooltip_clear_flag=True):
        self.text_edit = text_edit
        self.tooltip_clear_flag = tooltip_clear_flag
        # todo change empirical position to computed based on input area size
        self._tooltip_position = QPoint(0, 180)

    def _set_tooltip(self, message: str):
        QToolTip.showText(
            self.text_edit.mapToGlobal(
                self._tooltip_position
            ),
            message
        )

    def validate_compressed_pubkey(self, input_str: str):
        if self.tooltip_clear_flag:
            QToolTip.hideText()
        if len(input_str) > 2 and input_str[:2] not in ('02', '03'):
            self._set_tooltip('Wrong prefix for compressed pubkey')
            return ValidationState.INVALID
        if len(input_str) < 66:
            return ValidationState.INTERMEDIATE
        if len(input_str) > 66:
            self._set_tooltip('PubKey cropped because too long string passed')
            return ValidationState.INVALID
        return self.is_pubkey(input_str)

    def validate_uncompressed_pubkey(self, input_str: str):
        if self.tooltip_clear_flag:
            QToolTip.hideText()
        if len(input_str) > 2 and input_str[:2] != '04':
            self._set_tooltip('Wrong prefix for uncompressed pubkey')
            return ValidationState.INVALID
        if len(input_str) < 130:
            return ValidationState.INTERMEDIATE
        if len(input_str) > 130:
            self._set_tooltip('PubKey cropped because too long string passed')
            return ValidationState.INVALID
        return self.is_pubkey(input_str)

    def is_pubkey(self, pubkey_str: str) -> bool:
        try:
            pubkey_bytes = bytes.fromhex(pubkey_str)
        except ValueError:
            self._set_tooltip('Wrong pubkey format')
            return ValidationState.INVALID

        if not ECPubkey.is_pubkey_bytes(pubkey_bytes):
            self._set_tooltip('Wrong pubkey format')
            return ValidationState.INVALID

        return ValidationState.VALID


class RecoveryPubKeyDialog(QVBoxLayout):
    def __init__(self, parent, message_label):
        super().__init__()
        self.parent = parent
        label = message_label
        edit = QTextEdit()
        self.validator = PubKeyValidator(edit)
        edit.textChanged.connect(self._on_change)
        self.addWidget(label)
        self.addWidget(edit)
        self.edit = edit

    def _on_change(self):
        self.parent.next_button.setEnabled(False)
        pubkey_candidate= self.get_pubkey()
        state = self.validator.validate_uncompressed_pubkey(pubkey_candidate)
        if state == ValidationState.INVALID:
            self.validator.tooltip_clear_flag = False
            # delete last element to prevent showing new characters in input area
            self.edit.textCursor().deletePreviousChar()
        elif state == ValidationState.VALID:
            self.parent.next_button.setEnabled(True)
        elif state == ValidationState.INTERMEDIATE:
            self.validator.tooltip_clear_flag = True

    def get_pubkey(self):
        return self.edit.toPlainText()
