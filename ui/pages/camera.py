from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..services.config import CameraSettings
from ..widgets.common import PageSection, StatusBanner

PRESETS = {
    "Broadcast": CameraSettings(True, 0.82, 1.32, -0.12, 50.0, 2.5),
    "Tactical wide": CameraSettings(True, 0.72, 1.45, -0.15, 54.0, 2.5),
    "Action": CameraSettings(True, 1.05, 1.15, 0.0, 46.0, 2.5),
    "Stands": CameraSettings(True, 1.20, 0.95, 0.10, 42.0, 2.5),
    "Konami default": CameraSettings(True, 1.0, 1.0, 0.0, 50.0, 2.5),
}


class CameraControl(QWidget):
    def __init__(self, label: str, minimum: float, maximum: float, step: float, parent=None) -> None:
        super().__init__(parent)
        self.factor = round(1 / step)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)
        name = QLabel(label)
        name.setMinimumWidth(150)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(round(minimum * self.factor), round(maximum * self.factor))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(2 if step < 0.5 else 1)
        self.spin.setFixedWidth(92)
        self.slider.valueChanged.connect(lambda value: self.spin.setValue(value / self.factor))
        self.spin.valueChanged.connect(lambda value: self.slider.setValue(round(value * self.factor)))
        layout.addWidget(name)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)

    def value(self) -> float:
        return self.spin.value()

    def set_value(self, value: float) -> None:
        self.spin.setValue(value)


class CameraPage(QWidget):
    status_message = Signal(str)
    navigate_requested = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageBody")
        self.context = context
        self._loading = False
        self._dirty = False
        self._game_running = False
        self._hook_verified = False
        self._save_label = "Save for next launch"
        self._preset_group = QButtonGroup(self)
        self._preset_group.setExclusive(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(14)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.save_button = QPushButton("Save and apply")
        self.save_button.setProperty("role", "primary")
        self.save_button.setIcon(qta.icon("fa6s.floppy-disk", color="#FFFFFF"))
        self.save_button.clicked.connect(self.save)
        reload_button = QPushButton("Reload from sider.ini")
        reload_button.setIcon(qta.icon("fa6s.rotate", color="#17201C"))
        reload_button.clicked.connect(self.load)
        diagnostics_button = QPushButton("View diagnostics")
        diagnostics_button.setIcon(qta.icon("fa6s.stethoscope", color="#17201C"))
        diagnostics_button.clicked.connect(lambda: self.navigate_requested.emit("diagnostics"))
        toolbar.addWidget(self.save_button)
        toolbar.addWidget(reload_button)
        toolbar.addWidget(diagnostics_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.banner = StatusBanner()
        layout.addWidget(self.banner)

        body = QHBoxLayout()
        body.setSpacing(14)
        presets = PageSection("Profiles", "Known parameter sets")
        presets.setFixedWidth(250)
        self.active_profile = QLabel("Custom profile")
        self.active_profile.setObjectName("SectionMeta")
        presets.layout.addWidget(self.active_profile)
        for index, name in enumerate(PRESETS):
            button = QPushButton(name)
            button.setObjectName("PresetButton")
            button.setCheckable(True)
            button.setIcon(qta.icon("fa6s.video", color="#17201C"))
            button.clicked.connect(lambda _checked=False, preset=name: self.apply_preset(preset))
            self._preset_group.addButton(button, index)
            presets.layout.addWidget(button)
        presets.layout.addStretch(1)
        body.addWidget(presets)

        controls = PageSection(
            "Match camera parameters",
            "Saved to sider.ini. Live application requires a running, verified native hook.",
        )
        self.enabled = QCheckBox("Enable camera controller")
        controls.layout.addWidget(self.enabled)
        self.zoom = CameraControl("Zoom", 0.20, 2.50, 0.01)
        self.height = CameraControl("Height", 0.20, 2.50, 0.01)
        self.angle = CameraControl("Lens tilt", -0.50, 0.50, 0.01)
        self.fov = CameraControl("Field of view", 30.0, 85.0, 0.5)
        self.speed = CameraControl("Freecam speed", 0.5, 10.0, 0.1)
        for control in (self.zoom, self.height, self.angle, self.fov, self.speed):
            controls.layout.addWidget(control)
            control.spin.valueChanged.connect(self._mark_dirty)
        self.enabled.toggled.connect(self._mark_dirty)
        controls.layout.addStretch(1)
        body.addWidget(controls, 1)
        layout.addLayout(body, 1)
        self.load()

    def load(self) -> None:
        self._loading = True
        settings = self.context.config.read_camera()
        self._set(settings)
        self._loading = False
        self._set_dirty(False)
        self._preset_group.setExclusive(False)
        for button in self._preset_group.buttons():
            button.setChecked(False)
        self._preset_group.setExclusive(True)
        matching_name = next(
            (name for name, preset in PRESETS.items() if self._matches(settings, preset)),
            None,
        )
        if matching_name is not None:
            matching_index = tuple(PRESETS).index(matching_name)
            self._preset_group.button(matching_index).setChecked(True)
            self.active_profile.setText(f"Active: {matching_name}")
        else:
            self.active_profile.setText("Active: Custom profile")
        log = self.context.game.read_log_tail(500)
        self._game_running = self.context.game.status().running
        self._hook_verified = "[CAMERA DETOUR]" in log
        if self._hook_verified:
            self.banner.set_message("Camera detour telemetry is active in the latest native log.", "success")
        elif "[CAMERA] AOB pattern" in log:
            self.banner.set_message(
                "Camera signature matched, but no in-match detour call is logged yet.", "warning"
            )
        else:
            self.banner.set_message(
                "Camera hook is not verified. Open Diagnostics to inspect the native log.",
                "warning",
            )
        self._update_save_label()

    def save(self) -> None:
        settings = CameraSettings(
            enabled=self.enabled.isChecked(),
            zoom=self.zoom.value(),
            height=self.height.value(),
            angle=self.angle.value(),
            fov=self.fov.value(),
            freecam_speed=self.speed.value(),
        )
        self.context.config.save_camera(settings)
        self._set_dirty(False)
        if not self._game_running:
            message = "Camera profile saved for the next game launch."
        elif self._hook_verified:
            message = "Camera profile saved; the verified native hook will reload it live."
        else:
            message = "Camera profile saved, but live application is unverified. Check Diagnostics."
        self.banner.set_message(
            message, "success" if self._hook_verified or not self._game_running else "warning"
        )
        self.status_message.emit("Camera profile saved")

    def apply_preset(self, name: str) -> None:
        self._loading = True
        self._set(PRESETS[name])
        self._loading = False
        self.active_profile.setText(f"Selected: {name}")
        self._set_dirty(True)
        self.banner.set_message(f"Loaded {name}. Save and apply to make it active.", "info")

    def _set(self, settings: CameraSettings) -> None:
        self.enabled.setChecked(settings.enabled)
        self.zoom.set_value(settings.zoom)
        self.height.set_value(settings.height)
        self.angle.set_value(settings.angle)
        self.fov.set_value(settings.fov)
        self.speed.set_value(settings.freecam_speed)

    def _mark_dirty(self, _value=None) -> None:
        if not self._loading:
            self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self._update_save_label()

    def _update_save_label(self) -> None:
        if not self._game_running:
            self._save_label = "Save for next launch"
        elif self._hook_verified:
            self._save_label = "Save and apply live"
        else:
            self._save_label = "Save configuration"
        self.save_button.setText(f"{self._save_label} *" if self._dirty else self._save_label)

    @staticmethod
    def _matches(left: CameraSettings, right: CameraSettings) -> bool:
        return (
            left.enabled == right.enabled
            and abs(left.zoom - right.zoom) < 0.001
            and abs(left.height - right.height) < 0.001
            and abs(left.angle - right.angle) < 0.001
            and abs(left.fov - right.fov) < 0.001
            and abs(left.freecam_speed - right.freecam_speed) < 0.001
        )
