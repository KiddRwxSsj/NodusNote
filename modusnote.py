from __future__ import annotations

import io
import json
import math
import os
import random
import struct
import sys
import tempfile
import time
import uuid
import wave
from pathlib import Path
import winreg as reg

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

from PyQt6.QtCore import Qt, QEvent, QObject, QTimer, QSize, QTime
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QAction
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QSlider,
    QSystemTrayIcon,
    QTabWidget,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent / ".modus_data"
    BASE_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).resolve().parent / ".modus_data"
    BASE_DIR = Path(__file__).resolve().parent

STATE_FILE = APP_DIR / "state.json"
THEMES = ["Onyx", "Ivory", "Shadow Moses", "Python Eater", "Classic"]


def get_app_icon():
    """Busca el icono personalizado en la carpeta base."""
    ico_path = BASE_DIR / "nodus.ico"
    png_path = BASE_DIR / "NodusNote.png"
    
    if ico_path.exists():
        return QIcon(str(ico_path))
    elif png_path.exists():
        return QIcon(str(png_path))
        
    # Fallback al icono por defecto
    pm = QPixmap(32, 32)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setBrush(QColor("#fff"))
    p.drawRoundedRect(4, 4, 24, 24, 4, 4)
    p.end()
    return QIcon(pm)

def set_autostart(enable=True):
    key = reg.HKEY_CURRENT_USER
    key_value = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "ModusNote"

    if getattr(sys, "frozen", False):
        exe_path = f'"{sys.executable}"'
    else:
        exe_path = f'"{sys.executable.replace("python.exe", "pythonw.exe")}" "{os.path.abspath(__file__)}"'

    try:
        registry_key = reg.OpenKey(key, key_value, 0, reg.KEY_ALL_ACCESS)
        if enable:
            reg.SetValueEx(registry_key, app_name, 0, reg.REG_SZ, exe_path)
        else:
            try:
                reg.DeleteValue(registry_key, app_name)
            except FileNotFoundError:
                pass
        reg.CloseKey(registry_key)
    except Exception:
        pass


def check_autostart():
    try:
        registry_key = reg.OpenKey(
            reg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            reg.KEY_READ,
        )
        reg.QueryValueEx(registry_key, "ModusNote")
        reg.CloseKey(registry_key)
        return True
    except FileNotFoundError:
        return False


class AudioEngine:
    def __init__(self):
        self.enabled = True
        self.available = HAS_WINSOUND
        self.last_play = 0.0
        self.cooldowns = {
            "default": 0.030,
            "shadow_moses": 0.034,
            "python_eater": 0.040,
        }
        self.temp_dir = Path(tempfile.gettempdir()) / "modusnote_audio"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.sound_paths = {}

        if self.available:
            try:
                self._prepare_sounds()
            except Exception:
                self.available = False

    def set_enabled(self, enabled: bool):
        self.enabled = enabled

    def _build_wav(self, sampler, duration=0.012, sample_rate=22050):
        frames = max(1, int(sample_rate * duration))
        pcm = bytearray()

        for i in range(frames):
            t = i / sample_rate
            env = math.exp(-5.5 * i / frames)
            value = sampler(t, i, frames) * env
            value = max(-1.0, min(1.0, value))
            pcm += struct.pack("<h", int(value * 32767))

        bio = io.BytesIO()
        with wave.open(bio, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm)
        return bio.getvalue()

    def _default_bytes(self):
        def sampler(t, i, frames):
            low = math.sin(2 * math.pi * 235 * t) * 0.0016
            body = math.sin(2 * math.pi * 320 * t) * 0.0006
            return low + body

        return self._build_wav(sampler, duration=0.012)

    def _shadow_moses_bytes(self):
        def sampler(t, i, frames):
            base = math.sin(2 * math.pi * 820 * t) * 0.0010
            upper = math.sin(2 * math.pi * 1240 * t) * 0.00035
            transient = 0.00075 if i < frames * 0.12 else 0.0
            return base + upper + transient

        return self._build_wav(sampler, duration=0.010)

    def _python_eater_bytes(self):
        def sampler(t, i, frames):
            tone = math.sin(2 * math.pi * 620 * t) * 0.00145
            upper = math.sin(2 * math.pi * 930 * t) * 0.00035
            noise = random.uniform(-0.00018, 0.00018)
            return tone + upper + noise

        return self._build_wav(sampler, duration=0.016)

    def _write_sound(self, name, data):
        path = self.temp_dir / f"{name}.wav"
        path.write_bytes(data)
        self.sound_paths[name] = str(path)

    def _prepare_sounds(self):
        self._write_sound("default", self._default_bytes())
        self._write_sound("shadow_moses", self._shadow_moses_bytes())
        self._write_sound("python_eater", self._python_eater_bytes())

    def play(self, theme_name: str):
        if not self.enabled or not self.available:
            return

        if theme_name == "Shadow Moses":
            key = "shadow_moses"
        elif theme_name == "Python Eater":
            key = "python_eater"
        else:
            key = "default"

        now = time.perf_counter()
        if now - self.last_play < self.cooldowns.get(key, 0.03):
            return

        path = self.sound_paths.get(key)
        if not path:
            return

        flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        winsound.PlaySound(path, flags)
        self.last_play = now

    def stop(self):
        if self.available:
            try:
                winsound.PlaySound(None, 0)
            except Exception:
                pass


class CustomSizeGrip(QSizeGrip):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.theme = "Onyx"
        self.accent = QColor("#00FFCC")

    def paintEvent(self, event):
        if self.theme in ["Onyx", "Ivory"]:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        if self.theme == "Shadow Moses":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.accent)
            p.drawRect(12, 12, 3, 3)
            p.drawRect(8, 12, 3, 3)
            p.drawRect(12, 8, 3, 3)
        elif self.theme == "Python Eater":
            p.setPen(QPen(QColor("#4d5236"), 2))
            p.drawLine(14, 4, 14, 14)
            p.drawLine(4, 14, 14, 14)
            p.drawLine(10, 8, 10, 10)
            p.drawLine(8, 10, 10, 10)
        elif self.theme == "Classic":
            for x, y in [(12, 12), (8, 12), (4, 12), (12, 8), (8, 8), (12, 4)]:
                p.fillRect(x, y, 2, 2, QColor("#FFFFFF"))
                p.fillRect(x - 1, y - 1, 2, 2, QColor("#808080"))


class PlainQTextEdit(QTextEdit):
    def insertFromMimeData(self, source):
        if source.hasText():
            self.insertPlainText(source.text())


class CustomIconBtn(QPushButton):
    def __init__(self, icon_type="menu"):
        super().__init__()
        self.icon_type = icon_type
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color = QColor("#888888")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.color)
        pen.setWidth(2)
        p.setPen(pen)

        if self.icon_type == "menu":
            p.drawLine(4, 7, 20, 7)
            p.drawLine(4, 12, 20, 12)
            p.drawLine(4, 17, 20, 17)
        elif self.icon_type == "add":
            p.drawLine(12, 4, 12, 20)
            p.drawLine(4, 12, 20, 12)
        elif self.icon_type == "info":
            p.drawEllipse(2, 2, 20, 20)
            p.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "?")
        elif self.icon_type == "trash":
            pen.setWidth(1)
            p.setPen(pen)
            p.drawLine(5, 6, 19, 6)
            p.drawLine(9, 6, 9, 4)
            p.drawLine(15, 6, 15, 4)
            p.drawLine(9, 4, 15, 4)
            p.drawRoundedRect(6, 7, 12, 13, 2, 2)
            p.drawLine(9, 10, 9, 17)
            p.drawLine(12, 10, 12, 17)
            p.drawLine(15, 10, 15, 17)
        elif self.icon_type == "color_dot":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.color)
            p.drawEllipse(4, 4, 16, 16)


class LockBtn(QPushButton):
    def __init__(self):
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme = "Onyx"
        self.locked = False
        self.accent = QColor("#888")
        self.setFixedSize(20, 20)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.theme in ["Onyx", "Ivory"]:
            c = self.accent if self.locked else QColor("#555" if self.theme == "Onyx" else "#ccc")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(6, 6, 8, 8)
        elif self.theme == "Shadow Moses":
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            c = self.accent if self.locked else QColor("transparent")
            p.setPen(self.accent)
            p.setBrush(c)
            p.drawRect(5, 5, 10, 10)
            if self.locked:
                p.fillRect(7, 7, 6, 6, QColor("#000"))
        elif self.theme == "Python Eater":
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.setPen(self.accent)
            p.setBrush(QColor("#1b1c14"))
            p.drawRect(4, 4, 12, 12)
            if self.locked:
                p.fillRect(6, 6, 8, 8, self.accent)
        elif self.theme == "Classic":
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            bg = QColor("#E35B5B") if self.locked else QColor("#D8D2BD")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRect(2, 2, 16, 16)
            p.setPen(QColor("#FFFFFF"))
            p.drawLine(2, 2, 17, 2)
            p.drawLine(2, 2, 2, 17)
            p.setPen(QColor("#808080"))
            p.drawLine(2, 17, 17, 17)
            p.drawLine(17, 2, 17, 17)
            if self.locked:
                p.setPen(QPen(QColor("#fff"), 2))
                p.drawLine(6, 6, 14, 14)
                p.drawLine(14, 6, 6, 14)


class TechBars(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(80, 16)
        self.values = [0.1] * 8
        self.targets = [random.uniform(0.15, 0.9) for _ in range(8)]
        self.c = QColor("#00e5ff")
        self.theme = "Shadow Moses"
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

    def set_running(self, on):
        if self.theme == "Python Eater":
            if self.timer.isActive():
                self.timer.stop()
            self.update()
            return

        if self.theme != "Shadow Moses":
            if self.timer.isActive():
                self.timer.stop()
            self.update()
            return

        if on and not self.timer.isActive():
            self.timer.start(80)
        elif not on and self.timer.isActive():
            self.timer.stop()
            self.values = [0.1] * 8
            self.update()

    def tick(self):
        for i, val in enumerate(self.values):
            if abs(val - self.targets[i]) < 0.05:
                self.targets[i] = random.uniform(0.15, 1.0)
            self.values[i] += (self.targets[i] - val) * 0.32
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rect = self.rect()

        if self.theme == "Python Eater":
            p.setPen(QPen(self.c, 1))
            mid_y = rect.height() // 2
            p.drawLine(rect.left(), mid_y, rect.right(), mid_y)
            heights = [2, 5, 7, 3, 8, 3, 6, 4, 7, 2, 5, 8, 4, 3, 6, 2, 4, 7, 3, 5]
            idx = 0
            for x in range(rect.left() + 3, rect.right() - 2, 3):
                h = heights[idx % len(heights)]
                p.drawLine(x, mid_y - h // 2, x, mid_y + h // 2)
                idx += 1
            return

        if self.theme == "Shadow Moses":
            w = max(3, (rect.width() - 21) // 8)
            by = rect.bottom()
            for i, val in enumerate(self.values):
                h = int(max(2, rect.height() * val))
                c = QColor(self.c)
                c.setAlpha(170 if i % 2 == 0 else 255)
                x = rect.x() + i * (w + 3)
                p.fillRect(x, by - h, w, h, c)
                if i < 7:
                    p.fillRect(x, by - h - 2, w, 1, QColor(255, 255, 255, 45))


class TypingSoundFilter(QObject):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.ignore_keys = {
            Qt.Key.Key_Shift,
            Qt.Key.Key_Control,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
            Qt.Key.Key_CapsLock,
            Qt.Key.Key_Tab,
            Qt.Key.Key_Escape,
        }
        self.allowed_special = {
            Qt.Key.Key_Backspace,
            Qt.Key.Key_Delete,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        }

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.isAutoRepeat():
                return False
            if event.key() in self.ignore_keys:
                return False
            if event.text() or event.key() in self.allowed_special:
                self.main_app.audio.play(self.main_app.theme_box.currentText())
        return False


class TaskWidget(QWidget):
    def __init__(self, text="", time_str="", checked=False, parent_list=None, item_ref=None, save_cb=None, sound_filter=None):
        super().__init__()
        self.parent_list = parent_list
        self.item_ref = item_ref
        self.save_cb = save_cb

        ly = QHBoxLayout(self)
        ly.setContentsMargins(0, 2, 0, 2)

        self.cb = QCheckBox()
        self.cb.setChecked(checked)
        self.cb.stateChanged.connect(self.trigger_save)

        self.txt = QLineEdit(text)
        self.txt.setPlaceholderText("New task...")
        self.txt.textChanged.connect(self.trigger_save)
        if sound_filter:
            self.txt.installEventFilter(sound_filter)

        self.tm = QTimeEdit()
        self.tm.setDisplayFormat("HH:mm")
        self.tm.setButtonSymbols(QTimeEdit.ButtonSymbols.NoButtons)
        self.tm.setFixedWidth(50)
        if time_str:
            self.tm.setTime(QTime.fromString(time_str, "HH:mm"))
        self.tm.timeChanged.connect(self.trigger_save)

        self.btn_del = CustomIconBtn("trash")
        self.btn_del.setFixedSize(24, 24)
        self.btn_del.clicked.connect(self.delete_self)

        ly.addWidget(self.cb)
        ly.addWidget(self.txt)
        ly.addWidget(self.tm)
        ly.addWidget(self.btn_del)
        self.update_strike()

    def trigger_save(self):
        if self.save_cb:
            self.save_cb()
        self.update_strike()

    def update_strike(self):
        style = "line-through" if self.cb.isChecked() else "none"
        self.txt.setStyleSheet(f"text-decoration: {style};")

    def delete_self(self):
        self.parent_list.takeItem(self.parent_list.row(self.item_ref))
        self.trigger_save()


class ModusNote(QMainWindow):
    def __init__(self):
        super().__init__()
        self._loading = False
        self._applying_theme = False
        self.state = self.load_state()
        self.current_id = self.state.get("current_id", list(self.state["notes"].keys())[0])
        self.drag_pos = None

        self.audio = AudioEngine()
        self.audio.set_enabled(self.state.get("sounds", True))

        self._save_tmr = QTimer(self)
        self._save_tmr.setSingleShot(True)
        self._save_tmr.setInterval(700)
        self._save_tmr.timeout.connect(self.on_idle)

        self.sound_filter = TypingSoundFilter(self)

        self.setMinimumSize(400, 300)
        
        # Set App Icon Before UI Build
        self.setWindowIcon(get_app_icon())
        
        self.update_window_flags(init=True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.build_ui()
        self.build_tray()
        self.restore_geometry()
        self.populate_sidebar()

        saved_theme = self.state.get("theme", "Onyx")
        if saved_theme == "Neon":
            saved_theme = "Shadow Moses"

        self.theme_box.setCurrentText(saved_theme)
        self.op_slider.setValue(int(self.state.get("opacity", 1.0) * 100))

        self.apply_theme()
        self.apply_opacity(self.op_slider.value(), save=False)
        self.apply_lock()
        self.tab_changed(self.tabs.currentIndex())

    def update_window_flags(self, init=False):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnBottomHint
        if self.state.get("locked", False):
            flags |= Qt.WindowType.WindowTransparentForInput

        self.setWindowFlags(flags)

        if not init:
            self.show()
            current_opacity = self.state.get("opacity", 1.0)
            if hasattr(self, "op_slider"):
                current_opacity = self.op_slider.value() / 100.0
            self.setWindowOpacity(current_opacity)

    def show_info(self):
        msg = QMessageBox(self)
        msg.setWindowIcon(get_app_icon())
        msg.setWindowTitle("About ModusNote")
        msg.setText("<b>ModusNote</b><br><br>Created by KiddRwxSsj<br>© 2026. All rights reserved.")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()

    def load_state(self):
        s = {
            "theme": "Onyx",
            "opacity": 1.0,
            "locked": False,
            "sounds": True,
            "tech_color": "#00FFCC",
            "mgs_color": "#729343",
            "notes": {},
        }

        if STATE_FILE.exists():
            try:
                s.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass

        if s.get("theme") == "Neon":
            s["theme"] = "Shadow Moses"

        if not s.get("notes"):
            s["notes"] = {
                str(uuid.uuid4()): {
                    "title": "Main Note",
                    "txt": "",
                    "todos": [],
                }
            }

        return s

    def save_current(self):
        if not hasattr(self, "current_id") or not self.current_id:
            return

        todos = []
        for i in range(self.todo_list.count()):
            item = self.todo_list.item(i)
            w = self.todo_list.itemWidget(item)
            if w:
                todos.append({
                    "text": w.txt.text(),
                    "time": w.tm.time().toString("HH:mm"),
                    "checked": w.cb.isChecked(),
                })

        self.state["notes"][self.current_id]["txt"] = self.note_edit.toPlainText()
        self.state["notes"][self.current_id]["todos"] = todos

    def save_state(self):
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            self.save_current()
            self.state.update({
                "theme": self.theme_box.currentText(),
                "opacity": round(self.op_slider.value() / 100, 2),
                "locked": self.state.get("locked", False),
                "sounds": self.state.get("sounds", True),
                "current_id": self.current_id,
                "geometry": {
                    "x": self.x(),
                    "y": self.y(),
                    "w": self.width(),
                    "h": self.height(),
                },
            })
            STATE_FILE.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def on_idle(self):
        self.tech_bars.set_running(False)
        self.save_state()

    def on_act(self):
        if self.theme_box.currentText() == "Shadow Moses":
            self.tech_bars.set_running(True)
        self._save_tmr.start()

    def restore_geometry(self):
        g = self.state.get("geometry")
        if g:
            self.setGeometry(g["x"], g["y"], g["w"], g["h"])
        else:
            self.resize(450, 350)

    def build_ui(self):
        c = QWidget()
        self.setCentralWidget(c)

        main_ly = QVBoxLayout(c)
        main_ly.setContentsMargins(10, 10, 10, 10)

        self.card = QFrame(objectName="Card")
        card_ly = QVBoxLayout(self.card)
        card_ly.setContentsMargins(0, 0, 0, 0)
        card_ly.setSpacing(0)
        main_ly.addWidget(self.card)

        self.header = QWidget(objectName="Header")
        self.header.setFixedHeight(40)
        h_ly = QHBoxLayout(self.header)
        h_ly.setContentsMargins(15, 0, 15, 0)

        self.btn_menu = CustomIconBtn("menu")
        self.btn_menu.clicked.connect(self.toggle_sidebar)

        self.lbl_title = QLabel("ModusNote")
        self.lbl_title.setObjectName("AppTitle")

        self.tech_bars = TechBars()

        self.btn_info = CustomIconBtn("info")
        self.btn_info.clicked.connect(self.show_info)

        self.btn_lock = LockBtn()
        self.btn_lock.clicked.connect(self.toggle_lock)

        h_ly.addWidget(self.btn_menu)
        h_ly.addSpacing(10)
        h_ly.addWidget(self.lbl_title)
        h_ly.addStretch()
        h_ly.addWidget(self.tech_bars)
        h_ly.addSpacing(15)
        h_ly.addWidget(self.btn_info)
        h_ly.addSpacing(5)
        h_ly.addWidget(self.btn_lock)
        card_ly.addWidget(self.header)

        self.body = QWidget()
        b_ly = QHBoxLayout(self.body)
        b_ly.setContentsMargins(0, 0, 0, 0)
        b_ly.setSpacing(0)

        self.sidebar = QFrame(objectName="Sidebar")
        self.sidebar.setFixedWidth(140)
        self.sidebar.hide()

        sb_ly = QVBoxLayout(self.sidebar)
        sb_ly.setContentsMargins(10, 10, 10, 10)

        self.notes_list = QListWidget(objectName="NotesList")
        self.notes_list.currentRowChanged.connect(self.load_selected)

        sb_tools = QHBoxLayout()
        self.btn_add = CustomIconBtn("add")
        self.btn_add.clicked.connect(self.new_note)
        self.btn_del = CustomIconBtn("trash")
        self.btn_del.clicked.connect(self.del_note)
        sb_tools.addWidget(self.btn_add)
        sb_tools.addStretch()
        sb_tools.addWidget(self.btn_del)

        sb_ly.addWidget(self.notes_list)
        sb_ly.addLayout(sb_tools)
        b_ly.addWidget(self.sidebar)

        self.content = QWidget()
        c_ly = QVBoxLayout(self.content)
        c_ly.setContentsMargins(15, 10, 15, 5)

        self.title_container = QWidget()
        title_ly = QVBoxLayout(self.title_container)
        title_ly.setContentsMargins(0, 0, 0, 0)

        self.note_title = QLineEdit()
        self.note_title.setObjectName("NoteTitle")
        self.note_title.setPlaceholderText("Note Title...")
        self.note_title.textChanged.connect(self.update_title)
        self.note_title.installEventFilter(self.sound_filter)
        title_ly.addWidget(self.note_title)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.tab_changed)

        self.note_edit = PlainQTextEdit()
        self.note_edit.textChanged.connect(self.on_act)
        self.note_edit.installEventFilter(self.sound_filter)
        self.tabs.addTab(self.note_edit, "Notes")

        todo_w = QWidget()
        todo_ly = QVBoxLayout(todo_w)
        todo_ly.setContentsMargins(0, 10, 0, 0)

        self.todo_list = QListWidget(objectName="TodoList")

        self.btn_add_task = QPushButton("+ Add Task")
        self.btn_add_task.setObjectName("BtnAdd")
        self.btn_add_task.clicked.connect(lambda: self.add_task())

        todo_ly.addWidget(self.todo_list)
        todo_ly.addWidget(self.btn_add_task)
        self.tabs.addTab(todo_w, "To-Do")

        c_ly.addWidget(self.title_container)
        c_ly.addSpacing(5)
        c_ly.addWidget(self.tabs)
        b_ly.addWidget(self.content)
        card_ly.addWidget(self.body)

        self.footer = QWidget(objectName="Footer")
        self.footer.setFixedHeight(35)
        f_ly = QHBoxLayout(self.footer)
        f_ly.setContentsMargins(15, 0, 0, 0)

        self.theme_box = QComboBox()
        self.theme_box.setObjectName("ThemeBox")
        self.theme_box.addItems(THEMES)
        self.theme_box.currentTextChanged.connect(self.apply_theme)

        self.btn_color = CustomIconBtn("color_dot")
        self.btn_color.clicked.connect(self.pick_color)

        self.op_slider = QSlider(Qt.Orientation.Horizontal)
        self.op_slider.setRange(20, 100)
        self.op_slider.setFixedWidth(80)
        self.op_slider.valueChanged.connect(self.apply_opacity)

        self.size_grip = CustomSizeGrip(self.footer)

        f_ly.addWidget(self.theme_box)
        f_ly.addWidget(self.btn_color)
        f_ly.addStretch()
        f_ly.addWidget(self.op_slider)
        f_ly.addSpacing(8)
        f_ly.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        card_ly.addWidget(self.footer)

    def build_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(get_app_icon())

        m = QMenu()
        m.addAction(QAction("Lock/Unlock", self, triggered=self.toggle_lock))

        self.sound_action = QAction("Typing Sounds", self, checkable=True)
        self.sound_action.setChecked(self.state.get("sounds", True))
        self.sound_action.triggered.connect(self.toggle_sounds)
        m.addAction(self.sound_action)

        self.autostart_action = QAction("Run at Windows Startup", self, checkable=True)
        self.autostart_action.setChecked(check_autostart())
        self.autostart_action.triggered.connect(self.toggle_autostart)
        m.addAction(self.autostart_action)

        m.addSeparator()
        m.addAction(QAction("Quit ModusNote", self, triggered=QApplication.instance().quit))

        self.tray.setContextMenu(m)
        self.tray.show()

    def toggle_sounds(self, checked):
        self.state["sounds"] = checked
        self.audio.set_enabled(checked)
        if not checked:
            self.audio.stop()
        self.save_state()

    def toggle_autostart(self, checked):
        set_autostart(checked)

    def tab_changed(self, index):
        self.title_container.setVisible(index == 0)

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def populate_sidebar(self):
        self._loading = True
        self.notes_list.clear()

        row = 0
        sel = 0
        for nid, data in self.state["notes"].items():
            item = QListWidgetItem(data["title"])
            item.setData(Qt.ItemDataRole.UserRole, nid)
            self.notes_list.addItem(item)
            if nid == self.current_id:
                sel = row
            row += 1

        self.notes_list.setCurrentRow(sel)
        self._loading = False
        self.load_selected(sel)

    def load_selected(self, idx):
        if self._loading or idx < 0:
            return

        self.save_current()
        item = self.notes_list.item(idx)
        if not item:
            return

        self.current_id = item.data(Qt.ItemDataRole.UserRole)
        data = self.state["notes"][self.current_id]

        self._loading = True
        self.note_title.setText(data["title"])
        self.note_edit.setPlainText(data.get("txt", ""))
        self.todo_list.clear()

        for t in data.get("todos", []):
            self.add_task(t.get("text", ""), t.get("time", ""), t.get("checked", False))

        self._loading = False

    def update_title(self, txt):
        if self._loading:
            return

        txt = txt.strip() or "Untitled"
        self.state["notes"][self.current_id]["title"] = txt

        item = self.notes_list.currentItem()
        if item:
            item.setText(txt)

        self.on_act()

    def new_note(self):
        self.save_current()
        nid = str(uuid.uuid4())
        self.state["notes"][nid] = {
            "title": "New Note",
            "txt": "",
            "todos": [],
        }
        self.current_id = nid
        self.populate_sidebar()

    def del_note(self):
        if len(self.state["notes"]) <= 1:
            self.state["notes"] = {
                str(uuid.uuid4()): {
                    "title": "Main Note",
                    "txt": "",
                    "todos": [],
                }
            }
        else:
            del self.state["notes"][self.current_id]

        self.current_id = list(self.state["notes"].keys())[0]
        self.populate_sidebar()

    def add_task(self, txt="", tm="", chk=False):
        item = QListWidgetItem(self.todo_list)
        item.setSizeHint(QSize(200, 32))
        widget = TaskWidget(txt, tm, chk, self.todo_list, item, self.on_act, self.sound_filter)
        self.todo_list.setItemWidget(item, widget)
        self.on_act()

    def pick_color(self):
        theme = self.theme_box.currentText()
        current = QColor(self.state.get("mgs_color", "#729343")) if theme == "Python Eater" else QColor(self.state.get("tech_color", "#00FFCC"))
        color = QColorDialog.getColor(current, self)
        if color.isValid():
            if theme == "Python Eater":
                self.state["mgs_color"] = color.name()
            elif theme == "Shadow Moses":
                self.state["tech_color"] = color.name()
            self.apply_theme()

    def apply_theme(self, _=None):
        if self._applying_theme:
            return

        self._applying_theme = True
        theme = self.theme_box.currentText()
        shadow = QColor(self.state.get("tech_color", "#00FFCC"))
        python_color = QColor(self.state.get("mgs_color", "#729343"))

        self.btn_color.setVisible(theme in ["Shadow Moses", "Python Eater"])
        self.tech_bars.theme = theme

        if theme == "Python Eater":
            self.tech_bars.setVisible(True)
            self.tech_bars.c = python_color
            self.btn_color.color = python_color
            self.tech_bars.set_running(True)
        elif theme == "Shadow Moses":
            self.tech_bars.setVisible(True)
            self.tech_bars.c = shadow
            self.btn_color.color = shadow
            self.tech_bars.set_running(True)
        else:
            self.tech_bars.setVisible(False)
            self.tech_bars.set_running(False)

        self.size_grip.theme = theme
        self.size_grip.accent = python_color if theme == "Python Eater" else shadow
        self.size_grip.update()

        if theme == "Onyx":
            bg = "rgba(20, 20, 20, 1.0)"
            fg = "#E2E8F0"
            acc = "#525252"
            bdr = "transparent"
            sb_bg = "rgba(15, 15, 15, 1.0)"
            font = "Segoe UI"
            radius = "12px"
            head_bg = bg
            combo_bg = "#2D2D2D"
            combo_fg = fg
            scroll_bg = "rgba(40, 40, 40, 0.5)"
            scroll_handle = "#555"
            list_sel_fg = fg
            btn_add_qss = f"background: {acc}; color: {fg}; border: none; padding: 8px; border-radius: 6px; margin-top: 10px; font-family: '{font}';"
        elif theme == "Ivory":
            bg = "rgba(255, 255, 255, 1.0)"
            fg = "#1A1A1A"
            acc = "#E5E5E5"
            bdr = "transparent"
            sb_bg = "rgba(245, 245, 245, 1.0)"
            font = "Segoe UI"
            radius = "12px"
            head_bg = bg
            combo_bg = "#F5F5F5"
            combo_fg = fg
            scroll_bg = "rgba(230, 230, 230, 0.5)"
            scroll_handle = "#ccc"
            list_sel_fg = fg
            btn_add_qss = f"background: {acc}; color: {fg}; border: none; padding: 8px; border-radius: 6px; margin-top: 10px; font-family: '{font}';"
        elif theme == "Shadow Moses":
            bg_c = QColor(shadow.red() // 12, shadow.green() // 12, shadow.blue() // 12)
            bg = f"rgba({bg_c.red()}, {bg_c.green()}, {bg_c.blue()}, 1.0)"
            sb_bg = f"rgba({max(0, bg_c.red() - 5)}, {max(0, bg_c.green() - 5)}, {max(0, bg_c.blue() - 5)}, 1.0)"
            fg = shadow.name()
            acc = shadow.name()
            bdr = f"rgba({shadow.red()},{shadow.green()},{shadow.blue()}, 0.28)"
            font = "Consolas"
            radius = "0px"
            head_bg = sb_bg
            combo_bg = sb_bg
            combo_fg = fg
            scroll_bg = sb_bg
            scroll_handle = acc
            list_sel_fg = "#000000"
            btn_add_qss = f"background: transparent; color: {acc}; border: 1px dashed {bdr}; padding: 8px; border-radius: 6px; margin-top: 10px; font-family: '{font}';"
        elif theme == "Python Eater":
            bg = "rgba(27, 28, 20, 1.0)"
            sb_bg = "rgba(18, 18, 13, 1.0)"
            fg = "#e3e1ce"
            acc = python_color.name()
            bdr = "#36382a"
            font = "Courier New"
            radius = "0px"
            head_bg = bg
            combo_bg = sb_bg
            combo_fg = fg
            scroll_bg = sb_bg
            scroll_handle = acc
            list_sel_fg = "#12120d"
            btn_add_qss = f"background: {sb_bg}; color: {fg}; border: 1px solid {bdr}; padding: 8px; margin-top: 10px; font-family: '{font}';"
        else:
            bg = "#ECE9D8"
            fg = "#000000"
            acc = "#316AC5"
            bdr = "#0046D5"
            sb_bg = "#D8D2BD"
            font = "Tahoma"
            radius = "0px"
            head_bg = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0058E6, stop:0.1 #3A93FF, stop:0.5 #288EFF, stop:1 #003FDA)"
            combo_bg = "#FFFFFF"
            combo_fg = "#000000"
            scroll_bg = "#D8D2BD"
            scroll_handle = "#C0C0C0"
            list_sel_fg = "#FFFFFF"
            btn_add_qss = f"background: #ECE9D8; color: #000; border: 1px solid #7F9DB9; padding: 4px; margin-top: 10px; font-family: '{font}';"

        icon_color = QColor("#ffffff") if theme == "Classic" else QColor(fg)
        self.btn_menu.color = icon_color
        self.btn_add.color = icon_color
        self.btn_del.color = icon_color
        self.btn_info.color = icon_color
        self.btn_lock.theme = theme
        self.btn_lock.accent = QColor(acc)

        self.btn_menu.update()
        self.btn_add.update()
        self.btn_del.update()
        self.btn_info.update()
        self.btn_lock.update()
        self.btn_color.update()

        qss = f"""
            #Card {{
                background-color: {bg};
                border: 1px solid {bdr if bdr != 'transparent' else 'rgba(0,0,0,0.05)'};
                border-radius: {radius};
            }}
            #Header {{
                background: {head_bg};
                border-top-left-radius: {radius};
                border-top-right-radius: {radius};
                border-bottom: 1px solid {bdr if theme not in ['Onyx', 'Ivory'] else 'transparent'};
            }}
            #Footer {{
                border-top: 1px solid {bdr if theme not in ['Onyx', 'Ivory'] else 'transparent'};
                border-bottom-left-radius: {radius};
                border-bottom-right-radius: {radius};
            }}
            #Sidebar {{
                background: {sb_bg};
                border-right: 1px solid {bdr if theme not in ['Onyx', 'Ivory'] else 'transparent'};
                border-bottom-left-radius: {radius};
            }}
            #AppTitle {{
                color: {'#fff' if theme in ['Classic', 'Shadow Moses'] else fg};
                font-family: '{font}';
                font-weight: {'bold' if theme not in ['Shadow Moses', 'Python Eater'] else 'normal'};
                font-size: 14px;
            }}
            #NoteTitle {{
                color: {fg};
                font-family: '{font}';
                font-size: 22px;
                font-weight: bold;
                background: transparent;
                border: none;
                padding-bottom: 5px;
            }}
            QTextEdit, QListWidget, QLineEdit, QTimeEdit {{
                background: transparent;
                color: {fg};
                border: none;
                font-family: '{font}';
                font-size: 13px;
            }}
            QScrollBar:vertical {{
                border: none;
                background: {scroll_bg};
                width: 10px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {scroll_handle};
                min-height: 20px;
                border-radius: {'5px' if theme in ['Onyx', 'Ivory'] else '0px'};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
            }}
            #NotesList::item {{
                padding: 8px;
                border-radius: 6px;
                color: {fg};
                margin-bottom: 2px;
            }}
            #NotesList::item:selected {{
                background: {acc if theme != 'Python Eater' else '#2e3022'};
                border-left: {'4px solid ' + acc if theme == 'Python Eater' else 'none'};
                color: {list_sel_fg if theme != 'Python Eater' else fg};
                font-weight: bold;
            }}
            #TodoList::item:selected {{
                background: {acc if theme != 'Python Eater' else '#2e3022'};
                color: {list_sel_fg if theme != 'Python Eater' else fg};
            }}
            QTabWidget::pane {{
                border: none;
                border-top: 1px solid {bdr if theme not in ['Onyx', 'Ivory'] else 'rgba(128,128,128,0.2)'};
            }}
            QTabBar::tab {{
                background: transparent;
                color: {fg};
                padding: 6px 15px;
                font-family: '{font}';
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                border-bottom: 2px solid {acc if theme not in ['Onyx', 'Ivory'] else fg};
                font-weight: bold;
            }}
            #BtnAdd {{
                {btn_add_qss}
            }}
            #BtnAdd:hover {{
                background: rgba(128,128,128,0.2);
            }}
            #ThemeBox {{
                color: {fg};
                font-family: '{font}';
                background: transparent;
                border: none;
                padding: 2px;
            }}
            #ThemeBox QAbstractItemView {{
                background-color: {combo_bg};
                color: {combo_fg};
                selection-background-color: {acc};
                border: 1px solid {bdr if bdr != 'transparent' else 'rgba(128,128,128,0.2)'};
                outline: none;
            }}
            QSlider {{
                background: transparent;
            }}
            QCheckBox {{
                color: {fg};
                font-family: '{font}';
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 2px solid {bdr if theme not in ['Onyx', 'Ivory'] else 'rgba(128,128,128,0.5)'};
                border-radius: {'0px' if theme in ['Shadow Moses', 'Classic', 'Python Eater'] else '4px'};
            }}
            QCheckBox::indicator:checked {{
                background: {acc if theme not in ['Onyx', 'Ivory'] else fg};
                border-color: {acc if theme not in ['Onyx', 'Ivory'] else fg};
            }}
            QSizeGrip {{
                background: transparent;
                image: none;
            }}
        """

        self.setStyleSheet(qss)
        self.apply_opacity(self.op_slider.value(), save=False)
        self.apply_lock()

        self._applying_theme = False

    def apply_opacity(self, val, save=True):
        opacity = max(0.20, min(1.0, val / 100.0))
        self.setWindowOpacity(opacity)
        if save and not self._loading and hasattr(self, "theme_box"):
            self.save_state()

    def toggle_lock(self):
        self.state["locked"] = not self.state.get("locked", False)
        self.save_state()
        self.apply_lock()

    def apply_lock(self):
        locked = self.state.get("locked", False)
        self.btn_lock.locked = locked
        self.btn_lock.update()
        self.update_window_flags()
        self.size_grip.setVisible(not locked)

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.header.geometry().contains(event.pos())
            and not self.state.get("locked", False)
        ):
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag_pos and not self.state.get("locked", False):
            self.move(event.globalPosition().toPoint() - self.drag_pos)

    def mouseReleaseEvent(self, event):
        self.drag_pos = None
        self.save_state()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ModusNote()
    window.show()
    sys.exit(app.exec())