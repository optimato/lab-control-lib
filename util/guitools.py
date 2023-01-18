from qtpy.QtWidgets import (QWidget,
                            QHBoxLayout,
                            QVBoxLayout,
                            QPushButton,
                            QLabel,
                            QSpinBox,
                            QGroupBox)
from qtpy.QtCore import QTimer, Qt, Signal
from napari_tools_menu import register_dock_widget

class BlinkLabel(QLabel):

    DEFAULT_COLORS = ['#33dd33', '#aaaaaa']
    disabled = Signal()
    SYMBOL = "☀"
    #SYMBOL = "⬤"

    def __init__(self, size=14, period=1., timeout=15., colors=None, parent=None):
        """
        A blinking circle showing the "live state" of a connection.

        size: font size
        period: blinking period
        timeout: if self.isalive is not called within timeout seconds, the status
                 is switched to "disabled" (self.enabled = False).
        colors: the two colors that the circle take when blinking.
        """

        super().__init__(parent)
        self.size = size
        self.period = period
        self.colors = colors or self.DEFAULT_COLORS
        self.setText(self.SYMBOL)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"QLabel {{ color : {self.colors[0]}; font: {self.size}pt;}}")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.toggle)
        if period:
            self.timer.start(int(self.period*500))
        self.live_timer = QTimer(self)
        self.live_timer.timeout.connect(self.not_alive)
        self.live_timer.start(int(timeout*1000))
        self.on = True
        self.enabled = True

    def toggle(self):
        self.on = not self.on
        self.setStyleSheet(
            f"QLabel {{ color : {self.colors[int(self.on)]}; font: {self.size}pt;}}")

    def start(self, period=None):
        self.is_alive()
        if self.enabled:
            return
        period = period or self.period
        if period is not None:
            self.period = period
            self.timer.start(int(1000*period))
        else:
            self.on = True
            self.toggle()
        self.is_alive()
        self.enabled = True

    def stop(self):
        if not self.enabled:
            return
        self.live_timer.stop()
        self.timer.stop()
        self.on = False
        self.toggle()
        self.enabled = False

    def is_alive(self):
        """
        Restart the live timer.
        """
        self.live_timer.stop()
        self.live_timer.start()

    def not_alive(self):
        """
        live_timer timed out.
        """
        self.stop()
        self.disabled.emit()


@register_dock_widget(menu="Utilities > Live View")
class LiveView(QWidget):
    """
    Napari dock widget to manage the incoming live views
    """
    liveModePause = Signal()
    liveModePlay = Signal()
    bufferSizeChange = Signal(int)

    PAUSE = "❚❚"
    PLAY = "▶"

    def __init__(self, napari_viewer):
        super().__init__()
        self.viewer = napari_viewer

        # GUI

        # Live view notifier
        self.setLayout(QVBoxLayout())
        self.view_label = QLabel("Live view", self)
        self.view_status = BlinkLabel(period=1.)
        self.view_status.start()
        self.pause_button = QPushButton(self.PAUSE)
        self.live = True

        row = QHBoxLayout()
        row.addWidget(self.view_label)
        row.addWidget(self.view_status)
        self.layout().addLayout(row)
        self.layout().addWidget(self.pause_button)

        self.buffer_group = QGroupBox("Buffer")
        self.buffer_group.setLayout(QHBoxLayout())
        self.buffer_spinbox = QSpinBox(self)
        self.buffer_spinbox.setEnabled(True)
        self.buffer_spinbox.setFixedWidth(50)
        self.buffer_spinbox.setMinimum(1)
        self.buffer_spinbox.setMaximum(50)
        self.buffer_spinbox.setSingleStep(1)
        self.buffer_spinbox.valueChanged.connect(self.bufferSizeChange.emit)
        self.buffer_spinbox_label = QLabel("frames", self)
        self.buffer_group.layout().addWidget(self.buffer_spinbox)
        self.buffer_group.layout().addWidget(self.buffer_spinbox_label)

        self.layout().addWidget(self.buffer_group)

        self.pause_button.clicked.connect(self.pause_button_clicked)

        self.view_status.disabled.connect(self.not_alive)

    def pause_button_clicked(self):
        """
        Toggle button state.
        """
        if self.live:
            self.live = False
            self.pause_button.setText(self.PLAY)
            self.liveModePause.emit()
        else:
            self.live = True
            self.view_status.start()
            self.pause_button.setText(self.PAUSE)
            self.liveModePlay.emit()

    def update_buffer_size(self, value):
        """
        Update buffer size on the GUI without emiting signal
        """
        self.buffer_spinbox.valueChanged.disconnect()
        self.buffer_spinbox.setValue(value)
        self.buffer_spinbox.valueChanged.connect(self.bufferSizeChange.emit)

    def is_alive(self):
        """
        Manages the blinking notifier.
        """
        if not self.live:
            return
        self.view_status.is_alive()

    def not_alive(self):
        """
        Called if the is_alive timed out.
        """
        self.live = True
        self.pause_button_clicked()