import datetime
import time
from enum import IntEnum

from PyQt5.QtCore import QRegExp
from PyQt5.QtGui import QRegExpValidator
from PyQt5.QtWidgets import QVBoxLayout, QLineEdit, QHBoxLayout, QLabel, QCheckBox, QPushButton

from electrum.base_wizard import GoBack
from electrum.gui.qt.installwizard import InstallWizard
from electrum.gui.qt.util import TaskThread
from electrum.i18n import _
from electrum.notification_connector import EmailApiWallet, ApiError, Connector
from electrum.util import UserCancelled


class AbstractLineEdit(QLineEdit):
    def __init__(self, regex_exp: QRegExp):
        super().__init__()
        validator = QRegExpValidator(regex_exp, self)
        self.setValidator(validator)

    def set_red(self):
        self.setStyleSheet(
            'border: 3px solid red; background-color: #FE8484;'
        )

    def set_normal(self):
        self.setStyleSheet('')


class PinInputFiled(AbstractLineEdit):
    def __init__(self):
        super().__init__(
            regex_exp=QRegExp('\\b[0-9]{4}\\b')
        )


class EmailInputFiled(AbstractLineEdit):
    def __init__(self):
        # todo check regex email validation
        super().__init__(
            regex_exp=QRegExp('\\b[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,4}\\b')
        )


class ErrorMessageMixin:
    def clear_error(self):
        self.error_label.setVisible(False)

    def set_error(self, message):
        self.error_label.setText(message)
        self.error_label.setStyleSheet('color: red')
        self.error_label.setVisible(True)


class InputFieldMixin:
    def input_edited(self):
        if self.input_edit.hasAcceptableInput():
            self.parent.next_button.setEnabled(True)
            self.input_edit.set_normal()
        else:
            self.parent.next_button.setEnabled(False)
            self.input_edit.set_red()
        if not self.input_edit.text():
            self.input_edit.set_normal()


class EmailNotification(QVBoxLayout, ErrorMessageMixin, InputFieldMixin):
    def __init__(self, parent, email='', error_msg='', show_skip_checkbox=True):
        super(). __init__()
        self.parent = parent
        label = QLabel(_(
            'If you want to receive email notifications, please enter your email address. We will send you information '
            'about your transaction statuses. You can always change or add it later in Tools. It will be saved in the '
            'Electrum Vault and used within the app.'
        ))
        label.setWordWrap(True)
        box = QHBoxLayout()
        email_label = QLabel(_('Email address:'))
        email_edit = EmailInputFiled()
        box.addWidget(email_label)
        box.addWidget(email_edit)
        email_edit.textChanged.connect(self.input_edited)
        self.input_edit = email_edit
        self.input_edit.setText(email)

        self.addWidget(label)
        self.addSpacing(10)
        self.addLayout(box)
        self.addSpacing(5)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        if error_msg:
            self.set_error(error_msg)
        if show_skip_checkbox:
            self.skip_checkbox = QCheckBox(_('Skip this step'))
            self.skip_checkbox.toggled.connect(self.skip_toggle)
            self.addWidget(self.skip_checkbox)
            self.addSpacing(5)
        self.addWidget(self.error_label)

    def skip_toggle(self, flag):
        self.parent.next_button.setEnabled(flag or self.input_edit.hasAcceptableInput())

    def is_skipped(self):
        try:
            return self.skip_checkbox.isChecked()
        except AttributeError:
            return False

    def email(self):
        return self.input_edit.text()


class PinConfirmation(QVBoxLayout, ErrorMessageMixin, InputFieldMixin):
    RESEND_COOL_DOWN_TIME = 30

    def __init__(self, parent, payload: dict, error_msg=''):
        super(). __init__()
        self.parent = parent
        self.payload = payload

        label = QLabel(_('Please enter the code we sent to: ') + f"<br><b>{payload['email']}</b>")
        label.setWordWrap(True)
        box = QHBoxLayout()
        code_label = QLabel(_('Code:'))
        pin_edit = PinInputFiled()
        box.addWidget(code_label)
        box.addWidget(pin_edit)
        pin_edit.textChanged.connect(self.input_edited)
        self.input_edit = pin_edit

        self.addWidget(label)
        self.addSpacing(10)
        self.addLayout(box)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        if error_msg:
            self.set_error(error_msg)

        self.thread = TaskThread(None)
        self.thread.finished.connect(self.deleteLater)
        hbox = QHBoxLayout()
        self.resend_button = QPushButton(_('Resend'))
        hbox.addStretch(1)
        hbox.addWidget(self.resend_button)
        self.resend_button.clicked.connect(self.resend_request)
        self.addSpacing(5)
        self.addLayout(hbox)
        self.addSpacing(5)
        self.addWidget(self.error_label)

    def resend_task(self):
        t0 = datetime.datetime.now()
        response = self.parent.connector.subscribe_email(**self.payload)
        t1 = datetime.datetime.now()
        elapsed_time = (t1 - t0).total_seconds()
        self.parent.connector.set_token(response)
        time.sleep(int(self.RESEND_COOL_DOWN_TIME - elapsed_time))

    def on_success(self, *args, **kwargs):
        self.resend_button.setEnabled(True)

    def on_error(self, error):
        self.set_error(f'<b>ERROR</b> {error}')
        self.resend_button.setEnabled(True)

    def resend_request(self):
        self.clear_error()
        self.thread.add(task=self.resend_task,
                        on_success=self.on_success,
                        on_error=self.on_error)
        self.resend_button.setEnabled(False)

    def pin(self):
        return int(self.input_edit.text())


class EmailNotificationWizard(InstallWizard):
    CONFIG_KEY = 'email_notifications'

    class State(IntEnum):
        BACK = 1
        NEXT = 2
        CONTINUE = 3
        ERROR = 4

    def __init__(self, wallet, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.wallet = EmailApiWallet.from_wallet(wallet)
        self.connector = Connector()
        self._email = ''
        self._error_message = ''
        self._payload = {}
        self.show_skip_checkbox = True
        if not self.check_if_wallet_in_config(kwargs.get('config', {}), wallet):
            self.save_email_to_config(None)

    @classmethod
    def check_if_wallet_in_config(cls, config, wallet):
        wallet = EmailApiWallet.from_wallet(wallet)
        data = config.get(cls.CONFIG_KEY, {})
        return wallet.hash() in data

    def save_email_to_config(self, email):
        data = self.config.get(self.CONFIG_KEY, {})
        data[self.wallet.hash()] = email
        self.config.set_key(self.CONFIG_KEY, data)

    def exec_layout(self, layout, title=None, back_button_name=None,
                    next_enabled=True):
        if back_button_name:
            self.back_button.setText(back_button_name)
        try:
            super().exec_layout(layout, title, raise_on_cancel=True, next_enabled=next_enabled)
        except UserCancelled:
            return self.State.ERROR
        except GoBack:
            return self.State.BACK

    def run_notification(self):
        what_next = self.State.BACK
        while what_next == self.State.BACK:
            what_next = self.run_single_view(self._choose_email)
            if what_next == self.State.NEXT:
                what_next = self.run_single_view(self.confirm_pin)
            else:
                break

    @staticmethod
    def run_single_view(method, max_attempts=None):
        what_next = EmailNotificationWizard.State.CONTINUE
        counter = 0
        while what_next == EmailNotificationWizard.State.CONTINUE:
            what_next = method()
            if max_attempts and counter > max_attempts:
                what_next == EmailNotificationWizard.State.ERROR
            counter += 1
        return what_next

    def _choose_email(self):
        layout = EmailNotification(
            self,
            email=self._email,
            error_msg=self._error_message,
            show_skip_checkbox=self.show_skip_checkbox
        )
        layout.input_edited()
        result = self.exec_layout(layout, _('Notifications'), next_enabled=self.next_button.isEnabled())
        if result:
            return result
        self._email = layout.email()
        if not layout.is_skipped():
            try:
                payload = {
                    'wallets': [self.wallet],
                    'email': layout.email(),
                    'language': self.config.get('language')
                }
                response = self.connector.subscribe_email(**payload)
                self.connector.set_token(response)
                self._payload = payload
                self._error_message = ''
                return self.State.NEXT
            except ApiError as e:
                self._error_message = str(e)
                return self.State.CONTINUE
        else:
            return self.State.ERROR

    def confirm_pin(self):
        layout = PinConfirmation(self, payload=self._payload, error_msg=self._error_message)
        result = self.exec_layout(layout, _('Confirm your email address'), next_enabled=False, back_button_name='Back')
        layout.thread.terminate()
        if result:
            self._error_message = ''
            return result
        try:
            self.connector.authenticate(layout.pin())
            self.save_email_to_config(self._email)
            return self.State.NEXT
        except ApiError as e:
            self._error_message = str(e)
            return self.State.CONTINUE


class EmailNotificationMixin:
    def __init__(self):
        self.show_skip_checkbox = False
        self.setWindowTitle(_('Notifications'))


class EmailNotificationDialog(EmailNotificationWizard, EmailNotificationMixin):
    def __init__(self, wallet, *args, **kwargs):
        kwargs['turn_off_icon'] = True
        EmailNotificationWizard.__init__(self, wallet, *args, **kwargs)
        EmailNotificationMixin.__init__(self)


class WalletInfoMixin:
    def _init_sub_unsub(self, dialog):
        self._info_dialog = dialog
        self._sub_thread = TaskThread(None)
        self._sub_thread.finished.connect(self.deleteLater)
        self.sub_unsub_button.clicked.connect(self._sub_unsub_click)

    def _sub_unsub_click(self):
        self._info_dialog.close()
        email_wizard = EmailNotificationDialog(
            self.wallet,
            parent=self,
            config=self.config,
            app=self.app,
            plugins=None,
        )
        email_wizard.run_notification()
        email_wizard.terminate()
