#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2013 ecdsa@github
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QPalette
from PyQt5.QtWidgets import (QVBoxLayout, QCheckBox, QHBoxLayout, QLineEdit,
                             QLabel, QCompleter, QDialog, QStyledItemDelegate)

from electrum.i18n import _
from electrum.mnemonic import Mnemonic, seed_type
import electrum.old_mnemonic

from .util import (Buttons, OkButton, WWLabel, ButtonsTextEdit, icon_path,
                   EnterButton, CloseButton, WindowModalDialog, ColorScheme)
from .qrtextedit import ShowQRTextEdit, ScanQRTextEdit
from .completion_text_edit import CompletionTextEdit
from ...keystore import bip39_is_checksum_valid


def seed_warning_msg(seed):
    return ''.join([
        "<p>",
        _("Please save these {0} words on paper (the order is important). "),
        _("This seed will allow you to recover your wallet."),
        "</p>",
        "<b>" + _("WARNING") + ":</b>",
        "<ul>",
        "<li>" + _("Never disclose your seed.") + "</li>",
        "<li>" + _("Never enter it on any website.") + "</li>",
        "<li>" + _("Do not store it electronically.") + "</li>",
        "</ul>"
    ]).format(len(seed.split()))


class SeedLayout(QVBoxLayout):

    def seed_options(self, import_gw_option):
        vbox = QVBoxLayout()
        # order matters when we align checkboxes to right
        if import_gw_option:
            cb_gw = QCheckBox(_('Gold Wallet seed'))
            cb_gw.toggled.connect(self.toggle_cb_gold_wallet)
            cb_gw.setChecked(self.is_gold_wallet_import)
            vbox.addWidget(cb_gw, alignment=Qt.AlignLeft)
            self.checkboxes['gw'] = cb_gw
            self.is_gold_wallet_import = cb_gw.isChecked()
        if 'bip39' in self.options:
            def f(b):
                if b:
                    msg = ' '.join([
                        '<b>' + _('Warning') + ':</b>  ',
                        _('BIP39 seeds can be imported in Electrum, so that users can access funds locked in other wallets.'),
                        _('We do not guarantee that BIP39 imports will always be supported in Electrum.'),
                    ])
                else:
                    msg = ''
                self.seed_warning.setText(msg)
            cb_bip39 = QCheckBox(_('BIP39 seed'))
            cb_bip39.toggled.connect(f)
            cb_bip39.toggled.connect(self.toggle_cb_bip39)
            cb_bip39.setChecked(self.is_bip39)
            vbox.addWidget(cb_bip39, alignment=Qt.AlignLeft)
            self.checkboxes['bip39'] = cb_bip39
        if 'ext' in self.options:
            cb_ext = QCheckBox(_('Extend this seed with custom words'))
            cb_ext.toggled.connect(self.toggle_cb_ext)
            cb_ext.setChecked(self.is_ext)
            vbox.addWidget(cb_ext, alignment=Qt.AlignLeft)
            self.checkboxes['ext'] = cb_ext
        self.addLayout(vbox)
        self.is_ext = cb_ext.isChecked() if 'ext' in self.options else False
        self.is_bip39 = cb_bip39.isChecked() if 'bip39' in self.options else False

    def toggle_cb_ext(self, flag: bool):
        self.is_ext = flag

    def toggle_cb_gold_wallet(self, flag: bool):
        self.is_gold_wallet_import = flag
        bip39 = self.checkboxes.get('bip39', None)
        if bip39 and bip39.isChecked() and flag:
            bip39.setChecked(False)
        self.on_edit()

    def toggle_cb_bip39(self, flag: bool):
        self.is_bip39 = flag
        gw = self.checkboxes.get('gw', None)
        if gw and gw.isChecked() and flag:
            gw.setChecked(False)
        self.on_edit()

    def show_default_options(self):
        for key, cb in self.checkboxes.items():
            if key == 'gw':
                cb.setVisible(True)
                continue
            cb.setVisible(False)
        self.seed_warning.setVisible(False)

    def show_advanced_options(self):
        for cb in self.checkboxes.values():
            cb.setVisible(True)
        self.seed_warning.setVisible(True)

    def __init__(self, seed=None, title=None, icon=True, msg=None, options=None,
                 is_seed=None, passphrase=None, parent=None, for_seed_words=True, imported_wallet=None):
        QVBoxLayout.__init__(self)
        self.parent = parent
        self.options = options
        if title:
            self.addWidget(WWLabel(title))
        if seed:  # "read only", we already have the text
            if for_seed_words:
                self.seed_e = ButtonsTextEdit()
            else:  # e.g. xpub
                self.seed_e = ShowQRTextEdit()
            self.seed_e.setReadOnly(True)
            self.seed_e.setText(seed)
        else:  # we expect user to enter text
            assert for_seed_words
            self.seed_e = CompletionTextEdit()
            self.seed_e.setTabChangesFocus(False)  # so that tab auto-completes
            self.is_seed = is_seed
            self.saved_is_seed = self.is_seed
            self.seed_e.textChanged.connect(self.on_edit)
            self.initialize_completer()

        self.seed_e.setContextMenuPolicy(Qt.PreventContextMenu)
        self.seed_e.setMaximumHeight(75)
        hbox = QHBoxLayout()
        hbox.addWidget(self.seed_e)
        if icon:
            logo = QLabel()
            logo.setPixmap(QPixmap(icon_path("seed.png"))
                           .scaledToWidth(64, mode=Qt.SmoothTransformation))
            logo.setMaximumWidth(60)
            hbox.addWidget(logo)

        self.addLayout(hbox)
        self.seed_warning = WWLabel('')

        # options
        self.is_bip39 = False
        self.is_ext = False
        self.is_gold_wallet_import = False
        self.checkboxes = {}
        import_gw = False
        if imported_wallet in ['standard', '2-key', '3-key']:
            self.is_gold_wallet_import = True
            import_gw = True
        if imported_wallet in ['2-key', '3-key']:
            self.options = options = ['ext']
        if options:
            self.seed_options(import_gw)
        if passphrase:
            hbox = QHBoxLayout()
            passphrase_e = QLineEdit()
            passphrase_e.setText(passphrase)
            passphrase_e.setReadOnly(True)
            hbox.addWidget(QLabel(_("Your seed extension is") + ':'))
            hbox.addWidget(passphrase_e)
            self.addLayout(hbox)
        self.addStretch(1)
        if msg:
            self.seed_warning.setText(seed_warning_msg(seed))
        self.addWidget(self.seed_warning)

    def initialize_completer(self):
        bip39_english_list = Mnemonic('en').wordlist
        old_list = electrum.old_mnemonic.words
        only_old_list = set(old_list) - set(bip39_english_list)
        self.wordlist = list(bip39_english_list) + list(only_old_list)  # concat both lists
        self.wordlist.sort()

        class CompleterDelegate(QStyledItemDelegate):
            def initStyleOption(self, option, index):
                super().initStyleOption(option, index)
                # Some people complained that due to merging the two word lists,
                # it is difficult to restore from a metal backup, as they planned
                # to rely on the "4 letter prefixes are unique in bip39 word list" property.
                # So we color words that are only in old list.
                if option.text in only_old_list:
                    # yellow bg looks ~ok on both light/dark theme, regardless if (un)selected
                    option.backgroundBrush = ColorScheme.YELLOW.as_color(background=True)

        self.completer = QCompleter(self.wordlist)
        delegate = CompleterDelegate(self.seed_e)
        self.completer.popup().setItemDelegate(delegate)
        self.seed_e.set_completer(self.completer)

    def get_seed(self):
        text = self.seed_e.text()
        seed = ' '.join(text.split())
        del text
        return seed

    def on_edit(self):
        s = self.get_seed()
        if self.is_bip39 or self.is_gold_wallet_import:
            b = bip39_is_checksum_valid(s)[0]
        else:
            b = bool(seed_type(s))
        self.parent.next_button.setEnabled(b)

        # disable suggestions if user already typed an unknown word
        for word in self.get_seed().split(" ")[:-1]:
            if word not in self.wordlist:
                self.seed_e.disable_suggestions()
                return
        self.seed_e.enable_suggestions()

class KeysLayout(QVBoxLayout):
    def __init__(self, parent=None, header_layout=None, is_valid=None, allow_multi=False):
        QVBoxLayout.__init__(self)
        self.parent = parent
        self.is_valid = is_valid
        self.text_e = ScanQRTextEdit(allow_multi=allow_multi)
        self.text_e.textChanged.connect(self.on_edit)
        if isinstance(header_layout, str):
            self.addWidget(WWLabel(header_layout))
        else:
            self.addLayout(header_layout)
        self.addWidget(self.text_e)

    def get_text(self):
        return self.text_e.text()

    def on_edit(self):
        valid = False
        try:
            valid = self.is_valid(self.get_text())
        except Exception as e:
            self.parent.next_button.setToolTip(f'{_("Error")}: {str(e)}')
        else:
            self.parent.next_button.setToolTip('')
        self.parent.next_button.setEnabled(valid)


class SeedDialog(WindowModalDialog):

    def __init__(self, parent, seed, passphrase):
        WindowModalDialog.__init__(self, parent, ('Electrum - ' + _('Seed')))
        self.setMinimumWidth(400)
        vbox = QVBoxLayout(self)
        title =  _("Your wallet generation seed is:")
        slayout = SeedLayout(title=title, seed=seed, msg=True, passphrase=passphrase)
        vbox.addLayout(slayout)
        vbox.addLayout(Buttons(CloseButton(self)))
