import copy
import json
from enum import IntEnum
from typing import List

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QVBoxLayout, QTextEdit, QLineEdit, QLabel, \
    QPushButton, QHBoxLayout, QFileDialog, QApplication

from electrum.ecc import ECPubkey, ECPrivkey
from electrum.i18n import _
from .qrcodewidget import QRCodeWidget, QRDialog
from .transaction_dialog import PreviewTxDialog
from ...three_keys import short_mnemonic
from .util import filter_non_printable, WindowModalDialog, get_parent_main_window
from ...transaction import PartialTransaction


class ValidationState(IntEnum):
    INVALID = 0
    VALID = 1
    INTERMEDIATE = 2
    CROPPED = 3


class PubKeyValidator:
    COMPRESSED_PREFIXES = ('02', '03')
    UNCOMPRESSED_PREFIXES = '04'
    COMPRESSED_PUBKEY_LENGTH = 66
    UNCOMPRESSED_PUBKEY_LENGTH = 130

    def __init__(self, text_edit: QTextEdit, error_label: QLabel, disallowed_pubkeys: List[str]):
        self.text_edit = text_edit
        self.error_label = error_label
        self.disallowed_pubkeys = disallowed_pubkeys

    def _set_label(self, message: str):
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def validate(self, input_str: str) -> ValidationState:
        # initial set to 3 for parsing and validating first 2 characters
        input_str = filter_non_printable(input_str)
        pubkey_max_length = 3
        self.error_label.setVisible(False)

        if len(input_str) > 2:
            prefix = input_str[:2]
            if prefix in self.COMPRESSED_PREFIXES:
                pubkey_max_length = self.COMPRESSED_PUBKEY_LENGTH
            elif prefix == self.UNCOMPRESSED_PREFIXES:
                pubkey_max_length = self.UNCOMPRESSED_PUBKEY_LENGTH
            else:
                self._set_label(_('Wrong prefix. It is neither compressed nor uncompressed'))
                return ValidationState.INVALID

        if len(input_str) < pubkey_max_length:
            return ValidationState.INTERMEDIATE
        if len(input_str) > pubkey_max_length:
            self._set_label(_('PubKey cropped because too long string passed'))
            return ValidationState.CROPPED
        return self.is_allowed_pubkey(input_str)

    def _fixup_too_long_pubkey(self, input_str: str, pubkey_max_length: int):
        pubkey = input_str[:pubkey_max_length]
        return self.validate(pubkey)

    def is_allowed_pubkey(self, pubkey_str: str) -> ValidationState:
        try:
            pubkey_bytes = bytes.fromhex(pubkey_str)
        except ValueError:
            self._set_label(_('Wrong pubkey format'))
            return ValidationState.INVALID

        if not ECPubkey.is_pubkey_bytes(pubkey_bytes):
            self._set_label(_('Wrong pubkey format'))
            return ValidationState.INVALID

        if ECPubkey(pubkey_bytes).get_public_key_hex() in self.disallowed_pubkeys:
            self._set_label(_('This public key was already used. Please generate a new one.'))
            return ValidationState.INVALID

        return ValidationState.VALID


class ErrorLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setStyleSheet("font-weight: bold; color: red")


class InsertPubKeyDialog(QVBoxLayout):
    def __init__(self, parent, message_label, disallowed_keys: List[str] = None):
        disallowed_keys = disallowed_keys or []
        super().__init__()
        self.parent = parent
        self._if_apply_validation_logic = True
        label = message_label
        edit = QTextEdit()
        error_label = ErrorLabel()

        self.validator = PubKeyValidator(edit, error_label, disallowed_keys)
        edit.textChanged.connect(self._on_change)
        self.addWidget(label)
        self.addWidget(edit)
        self.addWidget(error_label)
        self.edit = edit

    def _on_change(self):
        if self._if_apply_validation_logic:
            self._apply_validation_logic()
        else:
            self._if_apply_validation_logic = True

    def _delete_last_character_from_input(self):
        self._if_apply_validation_logic = False
        self.edit.textCursor().deletePreviousChar()

    def _apply_validation_logic(self):
        self.parent.next_button.setEnabled(False)
        pubkey_candidate = self._get_str()
        state = self.validator.validate(pubkey_candidate)
        if state == ValidationState.INVALID:
            self._delete_last_character_from_input()
        elif state == ValidationState.VALID:
            self.parent.next_button.setEnabled(True)
        elif state == ValidationState.CROPPED:
            self.parent.next_button.setEnabled(True)
            self._delete_last_character_from_input()

    def _get_str(self) -> str:
        return self.edit.toPlainText().replace('\n', '')

    def get_compressed_pubkey(self):
        bytes_ = bytes.fromhex(self._get_str())
        pubkey = ECPubkey(bytes_)
        return pubkey.get_public_key_hex(compressed=True)


class Qr2FaDialog(QVBoxLayout):

    def __init__(self, parent, title_label: str, pin_label: str, qr_data: dict):
        super().__init__()
        self.parent = parent
        self.pubkey = ECPrivkey(short_mnemonic.entropy_to_privkey(qr_data['entropy'])).get_public_key_hex()
        qr = QRCodeWidget(self.prepare_qr_data_for_display(qr_data))
        self.edit = QLineEdit()
        self.edit.setMaxLength(4)
        self.edit.setFixedWidth(50)
        self.edit.setFont(QFont("Monospace"))
        self.edit.textChanged.connect(self._on_change)
        self.addWidget(title_label, alignment=Qt.AlignCenter)
        self.addWidget(qr, alignment=Qt.AlignCenter)
        self.addWidget(pin_label, alignment=Qt.AlignCenter)
        self.addWidget(self.edit, alignment=Qt.AlignCenter)

    def _on_change(self):
        self.parent.next_button.setEnabled(False)
        self.pin_candidate = self.edit.text()
        if self.pubkey[-4:] == self.pin_candidate:
            self.parent.next_button.setEnabled(True)

    def get_pubkey(self) -> str:
        return self.pubkey

    @staticmethod
    def prepare_qr_data_for_display(qr_data: dict) -> dict:
        new_qr_data = copy.deepcopy(qr_data)
        new_qr_data['entropy'] = new_qr_data['entropy'].hex()
        return json.dumps(new_qr_data)


class PSBTDialog(WindowModalDialog):
    def __init__(self, data_chunks, parent: 'ElectrumWindow', invoice, chunk=0, title="Transaction QRCode",
                 show_text=False, description=''):
        WindowModalDialog.__init__(self, parent, title)

        data = data_chunks[chunk]
        vbox = QVBoxLayout()
        qrw = QRCodeWidget(data)

        if description:
            chunk_description = description
            if len(data_chunks) > 0:
                chunk_description += '\n' + _('Chunk') + ' %d/%d' % (chunk + 1, len(data_chunks))
            label = QLabel(chunk_description)
            label.setWordWrap(True)
            hbox2 = QHBoxLayout()
            hbox2.addWidget(label)
            vbox.addLayout(hbox2)

        vbox.addWidget(qrw, 1)
        if show_text:
            text = QTextEdit()
            text.setText(data)
            text.setReadOnly(True)
            vbox.addWidget(text)
        hbox = QHBoxLayout()
        hbox.addStretch(1)

        def print_qr():
            main_window = get_parent_main_window(self)
            if main_window:
                filename = main_window.getSaveFileName(_("Select where to save file"), "qrcode.png")
            else:
                filename, __ = QFileDialog.getSaveFileName(self, _("Select where to save file"), "qrcode.png")
            if not filename:
                return
            p = qrw.grab()  # FIXME also grabs neutral colored padding
            p.save(filename, 'png')
            self.show_message(_("QR code saved to file") + " " + filename)

        def copy_to_clipboard():
            p = qrw.grab()
            QApplication.clipboard().setPixmap(p)
            self.show_message(_("QR code copied to clipboard"))

        b = QPushButton(_("Copy"))
        hbox.addWidget(b)
        b.clicked.connect(copy_to_clipboard)

        b = QPushButton(_("Save"))
        hbox.addWidget(b)
        b.clicked.connect(print_qr)

        if chunk+1 == len(data_chunks):
            b = QPushButton(_("Close"))
            hbox.addWidget(b)
            b.clicked.connect(self.accept)
            b.setDefault(True)

        if 0 < chunk < len(data_chunks):
            b = QPushButton(_("< Prev"))
            hbox.addWidget(b)
            b.clicked.connect(self.show_prev)

        if chunk+1 < len(data_chunks):
            b = QPushButton(_("Next >"))
            hbox.addWidget(b)
            b.clicked.connect(self.show_next)

        vbox.addLayout(hbox)
        self.setLayout(vbox)
        self.data_chunks = data_chunks
        self.parent = parent
        self.invoice = invoice
        self.chunk = chunk
        self.title = title
        self.description = description

    def show_next(self):
        super().accept()
        d = PSBTDialog(self.data_chunks, self.parent, self.invoice, chunk=self.chunk+1, title=self.title, description=self.description)
        d.exec_()

    def show_prev(self):
        super().accept()
        d = PSBTDialog(self.data_chunks, self.parent, self.invoice, chunk=self.chunk-1, title=self.title, description=self.description)
        d.exec_()

    def accept(self):
        if self.invoice:
            self.parent.delete_invoice(self.invoice['id'])
        super().accept()

    def closeEvent(self, event):
        self.accept()
        event.accept()


class PreviewPsbtTxDialog(PreviewTxDialog):

    def __init__(self, make_tx, outputs, external_keypairs, *, window: 'ElectrumWindow', invoice):
        super().__init__(make_tx, outputs, external_keypairs, window=window, invoice=invoice)

    def do_broadcast(self):
        self.main_window.push_top_level_window(self)
        try:
            if self.is_2fa and (self.wallet.is_instant_mode() or self.wallet.is_recovery_mode()):
                self.main_window.show_psbt_qrcode(self.tx, invoice=self.invoice)
            else:
                self.main_window.broadcast_transaction(self.tx, invoice=self.invoice, tx_desc=self.desc)
        finally:
            self.main_window.pop_top_level_window(self)
        self.saved = True
        self.update()
