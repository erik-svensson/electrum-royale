from PyQt5.QtWidgets import QPushButton, QHBoxLayout

from electrum.gui.qt.util import Buttons
from electrum.i18n import _


class AdvancedOptionMixin:
    def _translate_advanced_options(self):
        self._SHOW_ADVANCED_TEXT = _('Show advanced')
        self._HIDE_ADVANCED_TEXT = _('Hide advanced')

    def _add_advanced_button(self):
        self._translate_advanced_options()
        self.advanced_button = QPushButton(self._SHOW_ADVANCED_TEXT)
        self.advanced_button.clicked.connect(self._toggle_button)
        layout = self.layout()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if isinstance(item, Buttons):
                layout.removeItem(item)
                break
        layout.addLayout(Buttons(
            self.advanced_button,
            self.back_button,
            self.next_button,
        ))
        self.advanced_button.setVisible(False)

    def _toggle_button(self):
        if self.advanced_button.text() == self._SHOW_ADVANCED_TEXT:
            self.advanced_button.setText(self._HIDE_ADVANCED_TEXT)
            self._advanced_show_function()
        else:
            self.advanced_button.setText(self._SHOW_ADVANCED_TEXT)
            self._default_show_function()

    def exec_advanced_layout(self, layout, default_show_function, advanced_show_function, title=None, raise_on_cancel=True, next_enabled=True):
        self._default_show_function = default_show_function
        self._advanced_show_function = advanced_show_function
        self.advanced_button.setVisible(True)
        result = self.exec_layout(layout, title, raise_on_cancel, next_enabled)
        self.advanced_button.setVisible(False)
        return result

    def _show_advanced_text(self):
        self.advanced_button.setText(self._SHOW_ADVANCED_TEXT)

    def _hide_advanced_text(self):
        self.advanced_button.setText(self._HIDE_ADVANCED_TEXT)

    @staticmethod
    def compute_window_id(*args):
        return ''.join(list(map(str, args)))


class LastChosenState:
    STATES = {}

    @classmethod
    def set_state(cls, id_, index):
        cls.STATES[hash(id_)] = index

    @classmethod
    def get_index(cls, id_):
        return cls.STATES.get(hash(id_), 0)

    @classmethod
    def clear(cls):
        cls.STATES = {}
