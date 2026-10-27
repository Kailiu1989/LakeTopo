"""Application-wide, reversible English/Chinese UI localisation.

Only presentation text is translated. Paths, editable values and combo-box
user data remain untouched so changing language cannot change a calculation.
"""

import re
import string

from PyQt5.QtCore import QEvent, QLocale, QObject, QSettings, QTranslator, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractButton, QApplication, QComboBox, QFileDialog, QGroupBox, QLabel,
    QLineEdit, QMessageBox, QTabWidget, QWidget,
)

from ui.translations import ZH_CN
from app_paths import resource_path


def _pattern(template):
    parts, fields = [], []
    for literal, name, _spec, _conversion in string.Formatter().parse(template):
        parts.append(re.escape(literal))
        if name is not None:
            fields.append(name)
            parts.append("(.+?)")
    return re.compile("".join(parts), re.DOTALL if "\n" in template else 0), fields


class _QtTranslator(QTranslator):
    def translate(self, context, source, disambiguation=None, n=-1):
        # Qt owns its file-picker and message-box strings. Returning an empty
        # string for unknown entries lets Qt fall back to its source text.
        return ZH_CN.get(source, "")


class LanguageManager(QObject):
    language_changed = pyqtSignal(str)

    def __init__(self, app, settings=None):
        super().__init__(app)
        self.settings = settings or QSettings("LakeTopo", "LakeTopo")
        saved = self.settings.value("ui/language", "en")
        self.language = saved if saved in ("en", "zh") else "en"
        self._qt_translator = _QtTranslator(self)
        self._qt_catalog = QTranslator(self)
        self._qt_catalog.load(str(resource_path("ui/locales/qt_zh_CN.qm")))
        self._reverse = {value: key for key, value in ZH_CN.items()}
        self._templates = []
        for source, translated in ZH_CN.items():
            if "{" in source:
                forward, names = _pattern(source)
                backward, reverse_names = _pattern(translated)
                self._templates.append((source, translated, forward, names, backward, reverse_names))
        self._refreshing = False
        app.installEventFilter(self)
        self._set_qt_language()

    def _set_qt_language(self):
        app = QApplication.instance()
        if self.language == "zh":
            app.installTranslator(self._qt_catalog)
            app.installTranslator(self._qt_translator)
            QLocale.setDefault(QLocale(QLocale.Chinese, QLocale.China))
        else:
            app.removeTranslator(self._qt_translator)
            app.removeTranslator(self._qt_catalog)
            QLocale.setDefault(QLocale(QLocale.English, QLocale.UnitedStates))

    def text(self, text, _depth=0):
        if not isinstance(text, str) or not text or _depth > 4:
            return text
        source = self._reverse.get(text, text)
        if self.language == "zh" and source in ZH_CN:
            return ZH_CN[source]
        if self.language == "en" and text in self._reverse:
            return source
        # Dynamic messages are matched as whole templates; captured filenames
        # and numbers are substituted verbatim, never searched and replaced.
        for english, chinese, forward, names, backward, reverse_names in self._templates:
            for pattern, fields in ((forward, names), (backward, reverse_names)):
                match = pattern.fullmatch(text)
                if match:
                    values = dict(zip(fields, match.groups()))
                    nested = {"error", "model", "operator", "label", "page", "choices"}
                    values = {key: self.text(value, _depth + 1) if key in nested else value
                              for key, value in values.items()}
                    target = chinese if self.language == "zh" else english
                    return target.format_map(values)
        # Messages assembled from lines (projection summaries, error details).
        if "\n" in text:
            return "\n".join(self.text(line, _depth + 1) for line in text.split("\n"))
        stripped = text.strip()
        if stripped != text:
            return text[:len(text) - len(text.lstrip())] + self.text(stripped, _depth + 1) + text[len(text.rstrip()):]
        if text.startswith("›  "):
            return "›  " + self.text(text[3:], _depth + 1)
        return text

    def set_language(self, language):
        if language not in ("en", "zh"):
            raise ValueError("Unsupported language: " + str(language))
        if language == self.language:
            return
        self.language = language
        self.settings.setValue("ui/language", language)
        self._set_qt_language()
        self.refresh_all()
        self.language_changed.emit(language)

    def refresh_widget(self, widget):
        if self._refreshing or widget.property("i18n_skip"):
            return
        self._refreshing = True
        try:
            def apply(getter, setter, value=None, target=widget):
                current = getattr(target, getter)() if value is None else value
                key = "i18n_" + getter
                previous = target.property(key)
                source = previous[0] if previous and current == previous[1] else current
                translated = self.text(source)
                if getattr(target, getter)() != translated:
                    getattr(target, setter)(translated)
                target.setProperty(key, [source, translated])

            for getter, setter in (("windowTitle", "setWindowTitle"), ("toolTip", "setToolTip"),
                                   ("statusTip", "setStatusTip"), ("whatsThis", "setWhatsThis"),
                                   ("accessibleName", "setAccessibleName"), ("accessibleDescription", "setAccessibleDescription")):
                apply(getter, setter)
            if isinstance(widget, (QLabel, QAbstractButton)):
                # fullName is a stable routing key for the help page.
                apply("text", "setText", widget.property("fullName") or None)
            elif isinstance(widget, QGroupBox):
                apply("title", "setTitle")
            elif isinstance(widget, QLineEdit):
                apply("placeholderText", "setPlaceholderText")
                if widget.property("selectedPaths") is not None:
                    apply("text", "setText")
            elif isinstance(widget, QComboBox):
                # Never translate directory/history entries inside QFileDialog.
                ancestor = widget.parent()
                while ancestor and not isinstance(ancestor, QFileDialog):
                    ancestor = ancestor.parent()
                if ancestor is None:
                    blocked = widget.blockSignals(True)
                    for index in range(widget.count()):
                        source = widget.itemData(index)
                        if isinstance(source, str):
                            widget.setItemText(index, self.text(source))
                    widget.blockSignals(blocked)
            elif isinstance(widget, QTabWidget):
                for index in range(widget.count()):
                    widget.setTabText(index, self.text(widget.tabText(index)))
            if isinstance(widget, QMessageBox):
                apply("text", "setText")
                apply("informativeText", "setInformativeText")
                apply("detailedText", "setDetailedText")
            for action in widget.actions():
                for getter, setter in (("text", "setText"), ("toolTip", "setToolTip"), ("statusTip", "setStatusTip")):
                    apply(getter, setter, target=action)
        finally:
            self._refreshing = False

    def refresh_all(self):
        for widget in QApplication.allWidgets():
            self.refresh_widget(widget)

    def eventFilter(self, obj, event):
        if isinstance(obj, QWidget) and event.type() in (QEvent.Show, QEvent.Polish, QEvent.LanguageChange, QEvent.ActionAdded):
            self.refresh_widget(obj)
        return False


def language_manager(settings=None):
    app = QApplication.instance()
    if app is None:
        return None
    if not hasattr(app, "_language_manager"):
        app._language_manager = LanguageManager(app, settings)
    return app._language_manager


def tr(text):
    manager = language_manager()
    return manager.text(text) if manager is not None else text


def localized(widget):
    """Localise a new control while retaining its exact English source text."""
    manager = language_manager()
    if manager is not None:
        manager.refresh_widget(widget)
    return widget


def configure_plot_fonts():
    """Use an installed CJK font for both embedded and exported charts."""
    from matplotlib import font_manager, rcParams
    installed = {font.name for font in font_manager.fontManager.ttflist}
    candidates = [name for name in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "SimSun") if name in installed]
    rcParams["font.family"] = candidates + ["DejaVu Sans"]
    rcParams["axes.unicode_minus"] = False


class _FigureTranslator(QObject):
    def __init__(self, figure):
        super().__init__(figure.canvas)
        self.figure = figure
        language_manager().language_changed.connect(self.refresh)

    def refresh(self, _language):
        from matplotlib.text import Text
        for artist in self.figure.findobj(Text):
            artist.set_text(tr(artist.get_text()))
        self.figure.canvas.draw_idle()


def track_plot_language(figure):
    """Keep a standalone Qt/Matplotlib result window in the app's language."""
    if isinstance(figure.canvas, QWidget):
        figure.canvas._language_translator = _FigureTranslator(figure)
