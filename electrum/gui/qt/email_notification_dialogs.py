import datetime
import time
from abc import ABC, abstractmethod
from collections import Callable
from enum import IntEnum

from PyQt5.QtCore import QRegExp
from PyQt5.QtGui import QRegExpValidator
from PyQt5.QtWidgets import QVBoxLayout, QLineEdit, QHBoxLayout, QLabel, QCheckBox, QPushButton

from electrum.base_wizard import GoBack
from electrum.gui.qt.installwizard import InstallWizard
from electrum.gui.qt.util import TaskThread, WaitingDialogWithCancel, WindowModalDialog
from electrum.i18n import _, convert_to_iso_639_1
from electrum.notification_connector import EmailNotificationWallet, EmailNotificationApiError, Connector, \
    EmailAlreadySubscribedError, NoMorePINAttemptsError, TokenError
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
            'about your transaction statuses.'
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


class ChangeEmailLayout(QVBoxLayout, ErrorMessageMixin, InputFieldMixin):
    def __init__(self, parent, current_email='', new_email='', error_msg=''):
        super().__init__()
        self.parent = parent
        self.current_email = current_email
        label = QLabel(
            _('You can change your email. It is used to send you transaction notifications from chosen wallet.')
        )
        label.setWordWrap(True)
        box = QHBoxLayout()
        current_email_label = QLabel(_('Current email') + f':<b>{current_email}</b>')
        email_label = QLabel(_('New email:'))
        email_edit = EmailInputFiled()
        box.addWidget(email_label)
        box.addWidget(email_edit)
        email_edit.textChanged.connect(self.input_edited)
        self.input_edit = email_edit
        self.input_edit.setText(new_email)

        self.addWidget(label)
        self.addSpacing(10)
        self.addWidget(current_email_label)
        self.addLayout(box)
        self.addSpacing(5)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        if error_msg:
            self.set_error(error_msg)
        self.addWidget(self.error_label)

    def email(self):
        return self.input_edit.text()

    def input_edited(self):
        super().input_edited()
        if self.email() == self.current_email:
            self.parent.next_button.setEnabled(False)
            self.input_edit.set_red()


class ResendStrategy(ABC):
    def __init__(self, parent: InstallWizard, connector: Connector):
        self.parent = parent
        self.connector = connector

    def on_error(self, error: EmailNotificationApiError):
        if self.apply_error_logic(error):
            self.parent.show_error(str(error))
            self.parent.loop.exit(1)

    @abstractmethod
    def apply_error_logic(self, error: EmailNotificationApiError) -> bool:
        raise NotImplementedError()

    @abstractmethod
    def resend(self):
        raise NotImplementedError()


class SingleMethodResendStrategy(ResendStrategy):
    def __init__(self, parent: InstallWizard, connector: Connector, api_request_method: Callable):
        super().__init__(parent=parent, connector=connector)
        self._api_request_method = api_request_method

    def apply_error_logic(self, error: EmailNotificationApiError) -> bool:
        return isinstance(error, TokenError)

    def resend(self):
        self._api_request_method()


class SwitchableResendStrategy(ResendStrategy):
    def __init__(self, parent: InstallWizard, connector: Connector, api_request_method: Callable):
        super().__init__(parent=parent, connector=connector)
        self._api_request_method = api_request_method
        self._run_main_flow_api_request = False

    def apply_error_logic(self, error: EmailNotificationApiError) -> bool:
        return isinstance(error, TokenError)

    def resend(self):
        if self._run_main_flow_api_request:
            self._api_request_method()
            self._run_main_flow_api_request = False
        else:
            self.connector.resend()

    def switch_to_main_flow_endpoint_request(self):
        self._run_main_flow_api_request = True


class PinConfirmationLayout(QVBoxLayout, ErrorMessageMixin, InputFieldMixin):

    def __init__(self, parent, email, error_msg=''):
        super(). __init__()
        self.parent = parent
        self.resend_strategy = parent.resend_strategy
        self.cool_down_thread = parent.cool_down_thread

        label = QLabel(_('To confirm the request, please enter the code we sent to') + f"<br><b>{email}</b>")
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

        self.send_request_thread = TaskThread(None)
        hbox = QHBoxLayout()
        if self.cool_down_thread.is_running():
            self.resend_button = QPushButton(self.cool_down_thread.get_formatted_left_time())
            self.resend_button.setEnabled(False)
        else:
            self.resend_button = QPushButton(_('Resend'))
        hbox.addStretch(1)
        hbox.addWidget(self.resend_button)
        self.resend_button.clicked.connect(self.resend_request)
        self.addSpacing(5)
        self.addLayout(hbox)
        self.addSpacing(5)
        self.addWidget(self.error_label)

    def on_error(self, errors):
        self.resend_strategy.on_error(errors[1])
        self.set_error(str(errors[1]))

    def resend_request(self):
        self.clear_error()
        self.cool_down_thread.run()
        self.send_request_thread.add(
            task=lambda: self.resend_strategy.resend(),
            on_success=lambda *args, **kwargs: None,
            on_error=self.on_error
        )

    def pin(self):
        return self.input_edit.text()

    def terminate_thread(self):
        self.send_request_thread.terminate()


class CoolDownThread:
    RESEND_COOL_DOWN_TIME = 30

    def __init__(self):
        self.elapsed_time = 0
        self.pin_layout = None
        self.thread = None

    def register_layout(self, layout: PinConfirmationLayout):
        self.pin_layout = layout

    def unregister_layout(self):
        self.pin_layout = None

    def _set_resend_button_status(self, text: str, enabled: bool):
        if self.pin_layout:
            self.pin_layout.resend_button.setText(text)
            self.pin_layout.resend_button.setEnabled(enabled)

    def get_left_time(self) -> int:
        return int(self.RESEND_COOL_DOWN_TIME - self.elapsed_time)

    def get_formatted_left_time(self) -> str:
        return f'{self.get_left_time():>2}s'

    def cool_down_task(self):
        t0 = datetime.datetime.now()
        while True:
            self.elapsed_time = (datetime.datetime.now() - t0).total_seconds()
            if self.get_left_time() < 1:
                break
            self._set_resend_button_status(self.get_formatted_left_time(), False)
            time.sleep(1)

    def on_success(self, *args, **kwargs):
        self._set_resend_button_status(_('Resend'), True)

    def run(self):
        self.thread = TaskThread(None)
        self.thread.add(
            task=self.cool_down_task,
            on_success=self.on_success,
            on_error=lambda *args, **kwargs: None,
        )

    def is_running(self) -> bool:
        return bool(self.elapsed_time)

    def terminate(self):
        self.elapsed_time = 0
        if self.thread:
            self.thread.terminate()


class EmailNotificationWizard(InstallWizard):
    class State(IntEnum):
        BACK = 1
        NEXT = 2
        CONTINUE = 3
        ERROR = 4
        SHOW_EMAIL_SUBSCRIBED = 5

    def __init__(self, wallet, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.email_notification_wallet = EmailNotificationWallet.from_wallet(wallet)
        self.wallet = wallet
        self.connector = Connector.from_config(self.config)
        self._email = ''
        self._error_message = ''
        self.resend_strategy = SingleMethodResendStrategy(parent=self, connector=self.connector, api_request_method=self._subscribe)
        self.cool_down_thread = CoolDownThread()
        self._auto_resend_request = False
        self.show_skip_checkbox = True

    def load_notification_email(self) -> str:
        return self.wallet.db.get('notification_email', '')

    def save_notification_email(self, email=None):
        if email is None:
            email = self._email
        self.wallet.db.put('notification_email', email)

    def exec_layout(self, layout, title=None, back_button_name=None,
                    next_enabled=True):
        self.back_button.setText(back_button_name if back_button_name else _('Cancel'))
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
                what_next = self.run_single_view(self.confirm_pin, back_button_name=_('Back'))
            else:
                break

        if what_next == self.State.NEXT:
            self.save_notification_email()
            self.show_message(
                title=_('Success'),
                msg=_('You have successfully subscribed wallet to notifications'),
                rich_text=True,
            )
        elif what_next == self.State.SHOW_EMAIL_SUBSCRIBED:
            self.save_notification_email()
            self.show_message(
                title=_('Success'),
                msg=self._error_message + '\n' + _('You have successfully added your email address.'),
                rich_text=True,
            )

    @staticmethod
    def run_single_view(method, *args, **kwargs):
        what_next = EmailNotificationWizard.State.CONTINUE
        while what_next == EmailNotificationWizard.State.CONTINUE:
            what_next = method(*args, **kwargs)
        return what_next

    def _subscribe(self):
        response = self.connector.subscribe_wallet(
            wallets=[self.email_notification_wallet],
            email=self._email,
            language=convert_to_iso_639_1(self.config.get('language'))
        )
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
                    self.save_notification_email()
                    return self.State.SHOW_EMAIL_SUBSCRIBED
                return self.State.CONTINUE
        else:
            return self.State.ERROR

    def confirm_pin(self, back_button_name=None, email='', layout_title=''):
        layout = PinConfirmationLayout(self, email=email if email else self._email, error_msg=self._error_message)
        self.cool_down_thread.register_layout(layout)
        self.auto_resend_logic(layout=layout)
        result = self.exec_layout(
            layout,
            _('Confirm your email address') if not layout_title else layout_title,
            next_enabled=False,
            back_button_name=back_button_name
        )
        layout.terminate_thread()
        self.cool_down_thread.unregister_layout()
        if result:
            self._error_message = ''
            self.cool_down_thread.terminate()
            return result
        try:
            self.connector.authenticate(layout.pin())
            self.cool_down_thread.terminate()
            return self.State.NEXT
        except EmailNotificationApiError as error:
            return self.apply_pin_error_logic(error)

    def auto_resend_logic(self, layout):
        if self._auto_resend_request:
            self._auto_resend_request = False
            self.cool_down_thread.terminate()
            layout.resend_request()

    def apply_pin_error_logic(self, error: EmailNotificationApiError):
        self._error_message = str(error)
        if isinstance(error, (NoMorePINAttemptsError, TokenError)):
            self.show_error(msg=str(error), parent=self, rich_text=True)
            self._auto_resend_request = True
        return self.State.CONTINUE


class EmailNotificationDialog(EmailNotificationWizard):
    def __init__(self, wallet, *args, **kwargs):
        kwargs['turn_off_icon'] = True
        EmailNotificationWizard.__init__(self, wallet, *args, **kwargs)
        self.show_skip_checkbox = False
        self.setWindowTitle(_('Notifications'))


class UnsubscribeEmailNotificationDialog(EmailNotificationDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resend_strategy = SingleMethodResendStrategy(
            parent=self,
            connector=self.connector,
            api_request_method=self._unsubscribe
        )

    def confirm_pin(self, back_button_name=None, email=''):
        response = EmailNotificationWizard.run_single_view(
            super().confirm_pin,
            back_button_name=back_button_name,
            email=email,
        )
        if response == self.State.NEXT:
            self.save_notification_email('')
            self.show_message(
                title=_('Success'),
                msg=_('You have successfully unsubscribed wallet'),
                rich_text=True
            )
        self.terminate()
        return response

    def _unsubscribe(self):
        response = self.connector.unsubscribe_wallet(
            wallet_hashes=[self.email_notification_wallet.hash()],
            email=self._email,
        )
        self.connector.set_token(response)
        self._error_message = ''


class UpdateEmailNotificationDialog(EmailNotificationDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._new_email = ''
        self.resend_strategy = SwitchableResendStrategy(
            parent=self,
            connector=self.connector,
            api_request_method=self._modify,
        )
        self.State.SKIP_EMAIL_VIEW = 6

    def run_update(self):
        what_next = self.State.BACK
        while what_next in [self.State.BACK, self.State.SKIP_EMAIL_VIEW]:
            if what_next != self.State.SKIP_EMAIL_VIEW:
                what_next = self.run_single_view(self._change_email)
            if what_next in [self.State.NEXT, self.State.SKIP_EMAIL_VIEW]:
                what_next = self.run_single_view(
                    self.confirm_pin,
                    back_button_name=_('Back'),
                    layout_title=_('Confirm your current email address'),
                )
                if what_next == self.State.NEXT:
                    self._error_message = ''
                    what_next = self.run_single_view(
                        self.confirm_pin,
                        back_button_name=_('Back'),
                        email=self._new_email,
                        layout_title=_('Confirm your new email address'),
                    )
            else:
                break

        if what_next == self.State.NEXT:
            self.save_notification_email(self._new_email)
            self.show_message(
                title=_('Success'),
                msg=_('You have successfully updated your notification preferences'),
                rich_text=True,
            )

    def _modify(self):
        response = self.connector.modify_email(
            wallet_hashes=[self.email_notification_wallet.hash()],
            old_email=self._email,
            new_email=self._new_email,
        )
        self.connector.set_token(response)
        self._error_message = ''

    def _change_email(self):
        layout = ChangeEmailLayout(
            self,
            current_email=self._email,
            new_email=self._new_email,
            error_msg=self._error_message
        )
        layout.input_edited()
        result = self.exec_layout(layout, _('Change your email'), next_enabled=self.next_button.isEnabled())

        if result:
            return result
        self._new_email = layout.email()
        try:
            self._modify()
            return self.State.NEXT
        except EmailNotificationApiError as e:
            self._error_message = str(e)
            return self.State.CONTINUE

    def auto_resend_logic(self, layout):
        if self._auto_resend_request:
            self._auto_resend_request = False
            self.cool_down_thread.terminate()
            self.resend_strategy.switch_to_main_flow_endpoint_request()
            layout.resend_request()

    def apply_pin_error_logic(self, error: EmailNotificationApiError):
        state = super().apply_pin_error_logic(error)
        if self._auto_resend_request:
            return self.State.SKIP_EMAIL_VIEW
        return state


class WalletNotificationsMainDialog(WindowModalDialog, ErrorMessageMixin):
    def __init__(self, parent, config, wallet, app):
        super().__init__(parent, _('Email Notifications'))
        self.parent = parent
        self.setMinimumSize(500, 100)
        self.wallet = wallet
        self.config = config
        self.app = app
        vbox = QVBoxLayout()
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        vbox.addWidget(self.error_label)
        self.email = self.wallet.db.get('notification_email', '')
        vbox.addWidget(QLabel(
            _('It is used to send your transaction notifications from chosen wallet') + '\n' +
             (_('Email address: ') + self.email if self.email else _("Notification address hasn't been set yet"))
        ))
        hbox = QHBoxLayout()
        self.sub_unsub_button = QPushButton(_('Subscribe'))
        self.sub_unsub_button.setEnabled(False)
        self.update_button = QPushButton(_('Update'))
        self.update_button.clicked.connect(self._update)
        self.update_button.setEnabled(False)
        hbox.addStretch()
        hbox.addWidget(self.update_button)
        hbox.addWidget(self.sub_unsub_button)
        vbox.addLayout(hbox)
        self.setLayout(vbox)
        self.clear_error()

    def _subscribe(self):
        self.close()
        email_dialog = EmailNotificationDialog(
            self.wallet,
            parent=self.parent,
            config=self.config,
            app=self.app,
            plugins=None,
        )
        email_dialog.run_notification()
        email_dialog.terminate()

    def _unsubscribe(self):
        self.close()
        unsubscribe_dialog = UnsubscribeEmailNotificationDialog(
            wallet=self.wallet,
            parent=self.parent,
            config=self.config,
            app=self.app,
            plugins=None,
        )
        unsubscribe_dialog._email = self.email
        unsubscribe_dialog.close()

        if_unsub = unsubscribe_dialog.question(
            title=_('Unsubscribe from notifications'),
            msg=_('Do you want to unsubscribe this wallet from email notifications?')
        )
        if not if_unsub:
            return

        def task():
            unsubscribe_dialog._unsubscribe()

        def confirm(*args):
            unsubscribe_dialog.show()
            unsubscribe_dialog.confirm_pin()

        def on_error(*args):
            unsubscribe_dialog.show_error(str(args[0][1]))
            self.exec_()

        WaitingDialogWithCancel(
            self.parent,
            _('Connecting with server...'),
            task, confirm, on_error)

    def _update(self):
        self.close()
        update_dialog = UpdateEmailNotificationDialog(
            self.wallet,
            parent=self.parent,
            config=self.config,
            app=self.app,
            plugins=None,
        )
        update_dialog._email = self.email
        update_dialog.run_update()
        update_dialog.terminate()

    def check_subscription(self):
        connector = Connector.from_config(self.config)
        wallet = EmailNotificationWallet.from_wallet(self.wallet)
        is_subscribed = False
        if self.email:
            response = connector.check_subscription([wallet.hash()], self.email)
            is_subscribed = response['result'][0]
        self.sub_unsub_button.setEnabled(True)
        if is_subscribed:
            self.sub_unsub_button.setText(_('Unsubscribe'))
            self.sub_unsub_button.clicked.connect(self._unsubscribe)
            self.update_button.setEnabled(True)
        else:
            self.sub_unsub_button.clicked.connect(self._subscribe)

    def set_error(self, message):
        message = _('Error message: ') + message
        super().set_error(message)
