from datetime import datetime
from functools import partial

from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtWidgets import QVBoxLayout, QLabel, QPushButton, QWidget, QHBoxLayout, QLineEdit, \
    QTreeView, QAbstractItemView, QHeaderView, QStyleOptionButton, QStyle

from .confirm_tx_dialog import ConfirmTxDialog
from .util import read_QIcon, WaitingDialog
from .main_window import ElectrumWindow
from electrum.i18n import _
from ... import bitcoin
from ...plugin import run_hook
from ...transaction import PartialTxOutput, PartialTxInput, PartialTransaction
from ...util import bfh
from .recovery_list import RecoveryTab


class CheckableHeader(QHeaderView):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.parent = parent
        self.is_on = False

    def paintSection(self, painter: 'QPainter', rect: 'QRect', logical_index: int):
        painter.save()
        super().paintSection(painter, rect, logical_index)
        painter.restore()

        # assure set only in first column
        if logical_index == 0:
            option = QStyleOptionButton()
            option.rect = QRect(
                23, 3,
                14, 14
            )
            if self.is_on:
                option.state = QStyle.State_On
            else:
                option.state = QStyle.State_Off
            self.style().drawPrimitive(QStyle.PE_IndicatorCheckBox, option, painter)

    def mousePressEvent(self, event):
        if self.is_on:
            self.is_on = False
        else:
            self.is_on = True
        super().updateSection(0)
        super().mousePressEvent(event)


class TableItem(QStandardItem):
    def __init__(self, text, if_checkable=False):
        super().__init__(text)
        self.setCheckable(if_checkable)
        self.setTextAlignment(Qt.AlignRight)


class ElectrumARWindow(ElectrumWindow):
    LABELS = ['Date', 'Confirmation', 'Balance']

    def __init__(self, gui_object: 'ElectrumGui', wallet: 'Abstract_Wallet'):
        super().__init__(gui_object=gui_object, wallet=wallet)
        self.alert_transactions = []

        self.recovery_tab = self.create_recovery_tab(wallet, self.config)
        # todo add proper icon
        self.tabs.addTab(self.recovery_tab, read_QIcon('recovery.png'), _('Recovery'))

    def create_recovery_tab(self, wallet: 'Abstract_Wallet', config):
        return RecoveryTab(self, wallet, config)

    def recovery_onchain_dialog(self, inputs, outputs, recovery_keypairs):
        """Code copied from pay_onchain_dialog"""
        external_keypairs = None
        invoice = None
        # trustedcoin requires this
        if run_hook('abort_send', self):
            return
        is_sweep = bool(external_keypairs)
        make_tx = lambda fee_est: self.wallet.make_unsigned_transaction(
            coins=inputs,
            outputs=outputs,
            fee=fee_est,
            is_sweep=is_sweep)
        if self.config.get('advanced_preview'):
            self.preview_tx_dialog(make_tx, outputs, external_keypairs=external_keypairs, invoice=invoice)
            return

        output_values = [x.value for x in outputs]
        output_value = '!' if '!' in output_values else sum(output_values)
        d = ConfirmTxDialog(self, make_tx, output_value, is_sweep)
        d.update_tx()
        if d.not_enough_funds:
            self.show_message(_('Not Enough Funds'))
            return
        cancelled, is_send, password, tx = d.run()
        if cancelled:
            return
        if is_send:
            def sign_done(success):
                if success:
                    self.broadcast_or_show(tx, invoice=invoice)
            self.sign_tx_with_password(tx, sign_done, password, recovery_keypairs)
        else:
            self.preview_tx_dialog(make_tx, outputs, external_keypairs=external_keypairs, invoice=invoice)

    def sweep_key_dialog(self):
        self.wallet.set_alert()
        super().sweep_key_dialog()

    def pay_multiple_invoices(self, invoices):
        self.wallet.set_alert()
        super().pay_multiple_invoices(invoices)

    def do_pay_invoice(self, invoice):
        self.wallet.set_alert()
        super().do_pay_invoice(invoice)

    def show_recovery_tab(self):
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.recovery_tab))
