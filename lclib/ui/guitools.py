"""
Kind of plugins for the napari live viewer.

This file is part of lab-control-lib
(c) 2023-2024 Pierre Thibault (pthibault@units.it)
"""
from qtpy.QtWidgets import (QWidget,
                            QHBoxLayout,
                            QVBoxLayout,
                            QPushButton,
                            QLabel,
                            QSpinBox,
                            QGroupBox,
                            QCheckBox)
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
        if self.dark is None:
            dark = 0
        else:
            dark = self.dark
        if self.dark_apply_button.isChecked():
            out = data - dark
        else:
            out = data.astype('float64')
        if self.flat_apply_button.isChecked() and (self.flat is not None):
            f = self.flat - dark
            good = (f > 0)
            out[:, good] /= f[good]
            out[:, ~good] = 1.
        return out

    def dark_set_button_clicked(self):
        """
        Dark set button
        """
        layer, data = self._get_current_layer()
        if layer is not None:
            # We have a valid dark frame
            self.dark = data
            layer.name = 'dark'

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
        print(self.flat_apply_button.isChecked())
        if self.flat is None:
            self.flat_apply_button.setChecked(False)
        self.apply.emit()

    def flat_set_button_clicked(self):
        """
        Dark set button
        """
        layer, data = self._get_current_layer()
        if data is not None:
            # We have a valid flat frame
            self.flat = data
            layer.name = 'flat'
            # Notify
            self.flatSet.emit()

    def _get_current_layer(self):
        """
        Get the data from current layer if it is 2d.
        """
        # Fetch and current layer
        l =  self.viewer.layers.selection.active
        if l:
            if l.data.ndim == 2:
                data = l.data.copy()
            elif (l.data.ndim == 3) and (l.data.shape[0] == 1):
                data = l.data[0].copy()
            else:
                napari.utils.notifications.show_error("Selected layer is not 2D.")
                return None, None
        else:
            # We don't know what to do with multiple layers selected
            napari.utils.notifications.show_error("Select one layer.")
            return None, None

        return l, data

class StatusBar(QWidget):

    SCAN_COLOR = '#109010'
    SNAP_COLOR = '#101090'
    ROLL_COLOR = '#d06000'
    NONE_COLOR = '#000000'

    SCAN_TYPE_COLORS = {'SCAN': '#109010',
                        'SNAP': '#101090',
                        'ROLL': '#d06000',
                        '---': '#000000'}

    def __init__(self, napari_viewer):
        """
        """
        super().__init__()
        self.viewer = napari_viewer.v
        self.logger = napari_viewer.logger
        self.camera_name = napari_viewer.camera_name

        # Overall horizontal layout
        self.setLayout(QHBoxLayout())

        self.scan_type_label = QLabel('SCAN')
        self.scan_type_label.setObjectName('scan_type')
        self.scan_type_style_format = "QLabel#scan_type {{border: 0px white;\
                                                      border-style: outset;\
                                                      border-radius: 12px;\
                                                      background-color: {color};\
                                                      color: white;\
                                                      font: bold 16pt;}}"
        self.setStyleSheet(
                self.scan_type_style_format.format(color=self.SCAN_COLOR))
        self.scan_type_label.setFixedWidth(100)
        self.scan_type_label.setFixedHeight(45)
        self.scan_type_label.setAlignment(Qt.AlignCenter)
        self.layout().addWidget(self.scan_type_label, stretch=0)

        self.identifier_group = QGroupBox('identifier')
        self.identifier_group.setLayout(QVBoxLayout())
        self.identifier_label = QLabel('investigation/experiment/scan')
        self.identifier_group.layout().addWidget(self.identifier_label)
        self.layout().addWidget(self.identifier_group, stretch=2)

        """
        self.counter_group = QGroupBox('counter')
        self.counter_group.setLayout(QVBoxLayout())
        self.counter_label = QLabel('Number 54')
        self.counter_group.layout().addWidget(self.counter_label, stretch=1)
        self.layout().addWidget(self.counter_group)
        """
        self.exposure_group = QGroupBox('exposure')
        self.exposure_group.setLayout(QVBoxLayout())
        self.exposure_label = QLabel('0.5 s   (1/5)')
        self.exposure_label.setAlignment(Qt.AlignCenter)
        self.exposure_group.setFixedWidth(200)
        self.exposure_group.layout().addWidget(self.exposure_label)
        self.layout().addWidget(self.exposure_group, stretch=1)

        self.date_group = QGroupBox('date')
        self.date_group.setLayout(QVBoxLayout())
        self.date_label = QLabel('2023-02-04 22:38:28.807287')
        self.date_group.layout().addWidget(self.date_label, stretch=1)
        self.layout().addWidget(self.date_group)

        self.correction_group = QGroupBox('correction')
        self.correction_group.setLayout(QVBoxLayout())
        self.correction_label = QLabel('dark/flat')
        self.correction_label.setAlignment(Qt.AlignCenter)
        self.correction_group.setFixedWidth(100)
        self.correction_group.layout().addWidget(self.correction_label)
        self.layout().addWidget(self.correction_group, stretch=1)

    def update(self, *args, **kwargs):
        """
        Update info based on image metadata.
        """
        l = self.viewer.layers.selection.active
        if l is None:
            # No layer or multiple layers selected -
            self.logger.debug('Could not find active layer')
            self.wipe()
            return

        try:
            all_meta = l.metadata['meta']
        except KeyError:
            self.logger.debug('No metadata could be found.')
            self.wipe()
            return

        i = 0 if self.viewer.dims.ndim == 2 else int(self.viewer.dims.point[0])
        try:
            meta = all_meta[i]
        except IndexError:
            self.logger.debug(f'Error fetching metadata index {i}')
            self.wipe()
            return

        if meta is None:
            self.wipe()
            return

        # Build labels from metadata
        cam_meta = meta.get(self.camera_name)
        if not cam_meta:
            # Something is not right
            self.logger.debug(f'No camera {self.camera_name} entry has been found.')
            self.wipe()
            return

        identifier = "{investigation}/{experiment}".format(**meta['manager'])
        scan_name =  cam_meta.get('scan_name')
        if scan_name:
            scan_type = 'SCAN'
            identifier += '/' + scan_name
        else:
            filename = cam_meta.get('filename')
            if filename:
                scan_type = 'SNAP'
                identifier += '/{snap_counter}'.format(**cam_meta)
            else:
                scan_type = 'ROLL'

        date = cam_meta.get('acquisition_start', '????-??-?? ??:??:??.???')

        frame_counter = cam_meta.get('frame_counter')
        scan_counter = cam_meta.get('scan_counter')
        exposure_time = cam_meta.get('exposure_time', 0.0)
        exposure_number = cam_meta.get('exposure_number', 0)
        if scan_type == 'ROLL':
            exposure = f'FPS: {1/exposure_time:3.1f}'
        else:
            exposure = f"{exposure_time:3.2f} s"
        if scan_counter:
            exposure += f"  [{scan_counter}]"
        if frame_counter:
            exposure += f"  ({frame_counter}/{exposure_number})"
        else:
            exposure += f"  /{exposure_number}"

        self.set_labels(scan_type=scan_type,
                        identifier=identifier,
                        date=date,
                        exposure=exposure)

    def set_labels(self, scan_type='---',
                         date='---',
                         identifier='---/---',
                         exposure='-- s  (-/-)',
                         correction='---'):

        # Scan type
        self.scan_type_label.setText(scan_type)
        color = self.SCAN_TYPE_COLORS.get(scan_type, '#000000')
        self.setStyleSheet(
            self.scan_type_style_format.format(color=color))

        # identifier
        self.identifier_label.setText(identifier)

        # date
        self.date_label.setText(date)

        # exposure
        self.exposure_label.setText(exposure)

        # correction
        self.correction_label.setText(correction)

    def wipe(self):
        self.set_labels()

class Options(QWidget):

    def __init__(self, napari_viewer):
        """
        A Widget for random options. For now, toggle scale bar. Let's see how it evolves.
        """
        super().__init__()
        self.viewer = napari_viewer

        # Overall vertical layout
        self.setLayout(QVBoxLayout())

        # Scale bar group
        self.scalebar_group = QGroupBox("Scale Bar")
        self.scalebar_group.setLayout(QVBoxLayout())

        self.scalebar_check = QCheckBox('Scale')
        self.scalebar_check.setChecked(True)
        self.scalebar_group.layout().addWidget(self.scalebar_check)

        self.layout().addWidget(self.scalebar_group)

        """
        # Scale bar group
        self.contrast_group = QGroupBox("Contrast")
        self.contrast_group.setLayout(QVBoxLayout())
        """


        self.scalebar_check.stateChanged.connect(self.scalebar_toggle)
    def scalebar_toggle(self, event):
        """
        Turn on / off pixel physical units
        """
        self.viewer.update_scalebar(scaled=bool(event))