from qtpy.QtWidgets import (QWidget,
                            QHBoxLayout,
                            QVBoxLayout,
                            QPushButton,
                            QLabel,
                            QSpinBox,
                            QGroupBox)
from qtpy.QtCore import QTimer, Qt, Signal
import napari
import napari.utils.notifications
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
    averageRequest = Signal()

    PAUSE = "❚❚"
    PLAY = "▶"

    def __init__(self, napari_viewer):
        super().__init__()
        self.viewer = napari_viewer

        # GUI

        # Overall vertical layout
        self.setLayout(QVBoxLayout())

        # Live view notifier - horizontal
        row = QHBoxLayout()
        self.view_label = QLabel("Live view", self)
        self.view_status = BlinkLabel(period=1.)
        self.view_status.start()
        self.live = True
        row.addWidget(self.view_label)
        row.addWidget(self.view_status)
        self.layout().addLayout(row)

        # Pause button
        self.pause_button = QPushButton(self.PAUSE)
        self.layout().addWidget(self.pause_button)

        # Ring buffer group
        self.buffer_group = QGroupBox("Buffer")
        self.buffer_group.setLayout(QVBoxLayout())

        # Spinbox
        row = QHBoxLayout()
        self.buffer_spinbox = QSpinBox(self)
        self.buffer_spinbox.setEnabled(True)
        self.buffer_spinbox.setFixedWidth(50)
        self.buffer_spinbox.setMinimum(1)
        self.buffer_spinbox.setMaximum(50)
        self.buffer_spinbox.setSingleStep(1)
        self.buffer_spinbox_label = QLabel("frames", self)
        row.addWidget(self.buffer_spinbox)
        row.addWidget(self.buffer_spinbox_label)
        self.buffer_group.layout().addLayout(row)

        # Average button
        self.average_button = QPushButton("Average")
        self.buffer_group.layout().addWidget(self.average_button)
        self.layout().addWidget(self.buffer_group)

        # Connect all events
        self.view_status.disabled.connect(self.not_alive)
        self.pause_button.clicked.connect(self.pause_button_clicked)
        self.buffer_spinbox.valueChanged.connect(self.bufferSizeChange.emit)
        self.average_button.clicked.connect(self.averageRequest.emit)

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


class FrameCorrection(QWidget):
    """
    Dock widget dealing with flat/dark correction.
    """
    darkSet = Signal()
    flatSet = Signal()
    apply = Signal()

    def __init__(self, napari_viewer):
        super().__init__()
        self.viewer = napari_viewer

        self.dark = None
        self.flat = None
        self.active = True

        # GUI

        # Overall vertical layout
        self.setLayout(QVBoxLayout())

        # Dark frame group
        self.dark_group = QGroupBox("Dark frame")
        self.dark_group.setLayout(QHBoxLayout())

        self.dark_set_button = QPushButton('Set')
        self.dark_apply_button = QPushButton('Apply')
        self.dark_apply_button.setCheckable(True)

        self.dark_group.layout().addWidget(self.dark_set_button)
        self.dark_group.layout().addWidget(self.dark_apply_button)

        self.layout().addWidget(self.dark_group)

        # Flat frame group
        self.flat_group = QGroupBox("Flat frame")
        self.flat_group.setLayout(QHBoxLayout())

        self.flat_set_button = QPushButton('Set')
        self.flat_apply_button = QPushButton('Apply')
        self.flat_apply_button.setCheckable(True)

        self.flat_group.layout().addWidget(self.flat_set_button)
        self.flat_group.layout().addWidget(self.flat_apply_button)

        self.layout().addWidget(self.flat_group)

        # Connect events
        self.dark_set_button.clicked.connect(self.dark_set_button_clicked)
        self.flat_set_button.clicked.connect(self.flat_set_button_clicked)
        self.dark_apply_button.clicked.connect(self.dark_apply_button_clicked)
        self.flat_apply_button.clicked.connect(self.flat_apply_button_clicked)

    def correct(self, data):
        """
        Apply correction to data.
        """
        if self.dark_apply_button.isChecked() and (self.dark is not None):
            out = data - self.dark
        else:
            return data
        if self.flat_apply_button.isChecked() and (self.flat is not None):
            f = self.flat - self.dark
            good = (f > 0)
            out[:, good] /= f[good]
            out[:, ~good] = 1.
        return out

    def dark_set_button_clicked(self):
        """
        Dark set button
        """
        data = self._copy_current_layer_data()
        if data is not None:
            # We have a valid dark frame
            self.dark = data
            # Notify
            self.darkSet.emit()

    def dark_apply_button_clicked(self):
        """
        Dark apply button
        """
        if self.dark is None:
            self.dark_apply_button.setChecked(False)
            print(self.dark_apply_button.isChecked())
        else:
            self.apply.emit()

    def flat_apply_button_clicked(self):
        """
        Flat apply button: can be checke
        """
        if (self.flat is None) or (self.dark is None):
            self.flat_apply_button.setChecked(False)
        elif self.flat_apply_button.isChecked():
            if not self.dark_apply_button.isChecked():
                self.dark_apply_button.setChecked(True)
            self.apply.emit()

    def flat_set_button_clicked(self):
        """
        Dark set button
        """
        data = self._copy_current_layer_data()
        if data is not None:
            # We have a valid flat frame
            self.flat = data
            # Notify
            self.flatSet.emit()

    def _copy_current_layer_data(self):
        """
        Get the data from current layer if it is 2d.
        """
        # Fetch and current layer
        if l := self.viewer.layers.selection.active:
            if l.data.ndim == 2:
                data = l.data.copy()
            elif (l.data.ndim == 3) and (l.data.shape[0] == 1):
                data = l.data[0].copy()
            else:
                napari.utils.notifications.show_error("Selected layer is not 2D.")
                return
        else:
            # We don't know what to do with multiple layers selected
            napari.utils.notifications.show_error("Select one layer.")
            return

        return data

