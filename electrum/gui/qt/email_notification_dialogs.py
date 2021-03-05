import datetime
import time
from enum import IntEnum

from PyQt5.QtCore import QRegExp
from PyQt5.QtGui import QRegExpValidator
from PyQt5.QtWidgets import QVBoxLayout, QLineEdit, QHBoxLayout, QLabel, QCheckBox, QPushButton

from electrum.base_wizard import GoBack
from electrum.email_notification_config import EmailNotificationConfig
from electrum.gui.qt.installwizard import InstallWizard
from electrum.gui.qt.util import TaskThread, WaitingDialogWithCancel
from electrum.i18n import _, get_iso_639_1
from electrum.notification_connector import EmailNotificationWallet, EmailNotificationApiError, Connector, EmailAlreadySubscribedError
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
            # todo add ignore on '1lo0' signs
            regex_exp=QRegExp('\\b[0-9a-z]{4}\\b')
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


class EmailNotificationLayout(QVBoxLayout, ErrorMessageMixin, InputFieldMixin):
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


class PinConfirmationLayout(QVBoxLayout, ErrorMessageMixin, InputFieldMixin):
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

    def on_error(self, errors):
        self.set_error(str(errors[1]))
        self.resend_button.setEnabled(True)

    def resend_request(self):
        self.clear_error()
        self.thread.add(task=self.resend_task,
                        on_success=self.on_success,
                        on_error=self.on_error)
        self.resend_button.setEnabled(False)

    def pin(self):
        return self.input_edit.text()


class EmailNotificationWizard(InstallWizard):
    class State(IntEnum):
        BACK = 1
        NEXT = 2
        CONTINUE = 3
        ERROR = 4
        SHOW_EMAIL_SUBED = 5

    def __init__(self, wallet, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.wallet = EmailNotificationWallet.from_wallet(wallet)
        self.connector = Connector.from_config(self.config)
        self._email = ''
        self._error_message = ''
        self._payload = {}
        self.show_skip_checkbox = True

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
                EmailNotificationConfig.save_email_to_config(self.config, self.wallet, self._email)
                what_next = self.run_single_view(self.confirm_pin, _('Back'))
            elif what_next == self.State.SHOW_EMAIL_SUBED:
                self.show_message(self._error_message)
                break
            else:
                break

        if what_next in [self.State.NEXT, self.State.SHOW_EMAIL_SUBED]:
            self.show_message('<b>Success</b> <br><br> You have successfully subscribed wallet', rich_text=True)

    @staticmethod
    def run_single_view(method, *args, max_attempts=None):
        what_next = EmailNotificationWizard.State.CONTINUE
        counter = 0
        while what_next == EmailNotificationWizard.State.CONTINUE:
            what_next = method(*args)
            if max_attempts and counter > max_attempts:
                what_next = EmailNotificationWizard.State.ERROR
            counter += 1
        return what_next

    def _subscribe(self):
        payload = {
            'wallets': [self.wallet],
            'email': self._email,
            'language': get_iso_639_1(self.config.get('language'))
        }
        self._payload = payload
        response = self.connector.subscribe_email(**payload)
        self.connector.set_token(response)
        self._error_message = ''

    def _choose_email(self):
        layout = EmailNotificationLayout(
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
                self._subscribe()
                return self.State.NEXT
            except EmailNotificationApiError as e:
                self._error_message = str(e)
                if isinstance(e, EmailAlreadySubscribedError):
                    EmailNotificationConfig.save_email_to_config(self.config, self.wallet, self._email)
                    return self.State.SHOW_EMAIL_SUBED
                return self.State.CONTINUE
        else:
            return self.State.ERROR

    def confirm_pin(self, back_button_name=None):
        layout = PinConfirmationLayout(self, payload=self._payload, error_msg=self._error_message)
        result = self.exec_layout(layout, _('Confirm your email address'), next_enabled=False, back_button_name=back_button_name)
        layout.thread.terminate()
        if result:
            self._error_message = ''
            return result
        try:
            self.connector.authenticate(layout.pin())
            return self.State.NEXT
        except EmailNotificationApiError as e:
            self._error_message = str(e)
            return self.State.CONTINUE


class EmailNotificationDialog(EmailNotificationWizard):
    def __init__(self, wallet, *args, **kwargs):
        kwargs['turn_off_icon'] = True
        EmailNotificationWizard.__init__(self, wallet, *args, **kwargs)
        self.show_skip_checkbox = False
        self.setWindowTitle(_('Notifications'))

    def only_confirm_pin(self):
        response = EmailNotificationWizard.run_single_view(
            super().confirm_pin, None
        )
        if response == self.State.NEXT:
            self.show_message('<b>Success</b> <br><br> You have successfully subscribed wallet', rich_text=True)
        self.terminate()


class WalletInfoNotifications:
    def __init__(self, parent, config, wallet, app):
        self.parent = parent
        self.wallet = wallet
        self.config = config
        self.app = app
        self.sub_unsub_button = QPushButton()
        self.thread = TaskThread(None)
        self.email = ''

    @property
    def dialog(self):
        return self._dialog

    @dialog.setter
    def dialog(self, dialog):
        self._dialog = dialog

    def _subscribe(self):
        self.dialog.close()
        email_dialog = EmailNotificationDialog(
            self.wallet,
            parent=self.parent,
            config=self.config,
            app=self.app,
            plugins=None,
        )
        email_dialog.run_notification()
        email_dialog.terminate()

    # todo implement logic
    def _unsubscribe(self):
        pass

    def _subscribe_with_predefined_email(self):
        self.dialog.close()
        email_dialog = EmailNotificationDialog(
            self.wallet,
            parent=self.parent,
            config=self.config,
            app=self.app,
            plugins=None,
        )
        email_dialog._email = self.email
        email_dialog.close()

        def task():
            email_dialog._subscribe()

        def confirm(*args):
            email_dialog.show()
            email_dialog.only_confirm_pin()
            EmailNotificationConfig.save_email_to_config(self.config, self.wallet, self.email)

        def on_error(*args):
            email_dialog.show_error(str(args[0][1]))

        WaitingDialogWithCancel(
            self.parent,
            _('Connecting with server...'),
            task, confirm, on_error)

    def _disconnect(self):
        try:
            self.sub_unsub_button.clicked.disconnect()
        except TypeError:
            pass

    def sync_sub_unsub_button(self):
        email = EmailNotificationConfig.get_wallet_email(self.config, self.wallet)
        if email:
            self.email = email
            self.sub_unsub_button.setText(_('Loading...'))
            self.sub_unsub_button.setEnabled(False)
            self._check_subscription()
        else:
            self.sub_unsub_button.setText(_('Subscribe'))
            self._disconnect()
            self.sub_unsub_button.clicked.connect(self._subscribe)

    def _check_subscription(self):
        def on_error(*args, **kwargs):
            self.sub_unsub_button.setText(_('Error'))
            self.sub_unsub_button.setEnabled(False)

        def on_success(subscribed):
            if subscribed:
                self.sub_unsub_button.setText(_('Unsubscribe'))
                self._disconnect()
                self.sub_unsub_button.clicked.connect(self._unsubscribe)
            else:
                self.sub_unsub_button.setText(_('Subscribe'))
                self._disconnect()
                self.sub_unsub_button.clicked.connect(self._subscribe_with_predefined_email)
            self.sub_unsub_button.setEnabled(True)

        def task():
            connector = Connector.from_config(self.config)
            wallet = EmailNotificationWallet.from_wallet(self.wallet)
            response = connector.check_subscription([wallet.hash()], self.email)
            return response['result'][0]

        self.thread.add(
            task=task,
            on_success=on_success,
            on_error=on_error
        )
