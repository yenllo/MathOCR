import sys
import os
import warnings
warnings.filterwarnings("ignore")

# Permite arrancar desde cualquier directorio de trabajo: garantiza que los
# módulos hermanos (snipper, ocr_engine, gui) se resuelvan vía imports desnudos.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Redirigir sys.stdout y sys.stderr en pythonw.exe (modo sin consola) para evitar
# que librerías de Deep Learning (como doclayout_yolo / ultralytics) fallen al inspeccionar sys.stdout.encoding.
class DummyStream:
    def __init__(self):
        self.encoding = "utf-8"
    def write(self, data):
        pass
    def flush(self):
        pass
    def isatty(self):
        return False

if sys.stdout is None:
    sys.stdout = DummyStream()
if sys.stderr is None:
    sys.stderr = DummyStream()
from PyQt6.QtCore import pyqtSignal, QObject, Qt, QThread
from PyQt6.QtGui import QIcon, QAction, QPixmap
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from pynput import keyboard

# Local modules
from snipper import SnipperWindow
from ocr_engine import OCREngine, OCRWorker
from gui import ResultsWindow

class HotkeySignaler(QObject):
    """Bridge to safely emit Qt signals from the external pynput thread."""
    trigger_snipper = pyqtSignal()

class ModelLoaderThread(QThread):
    """Loads the heavy deep learning models in the background on startup."""
    loaded = pyqtSignal(bool)

    def __init__(self, ocr_engine):
        super().__init__()
        self.ocr_engine = ocr_engine

    def run(self):
        success = self.ocr_engine.initialize()
        self.loaded.emit(success)

class MathOCRApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        # Initialize modules
        self.ocr_engine = OCREngine()
        self.snipper = SnipperWindow()
        self.results_window = ResultsWindow()
        self.worker = None

        # Signaler for hotkeys
        self.signaler = HotkeySignaler()

        # Connect internal signals
        self.signaler.trigger_snipper.connect(self.activate_snipping)
        self.snipper.snipped.connect(self.process_snip)
        
        # Setup system tray icon and menu
        self.setup_tray()
        
        # Start loading the OCR engine in the background
        self.status_tray_message("Cargando MathOCR", "Inicializando el motor local de OCR matemáticos...")
        self.loader_thread = ModelLoaderThread(self.ocr_engine)
        self.loader_thread.loaded.connect(self.on_model_loaded)
        self.loader_thread.start()

        # Keyboard listener
        self.listener = None
        self.setup_hotkey()

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self.app)
        
        # Create a simple default icon for system tray (white square as fallback)
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        # Draw a beautiful custom icon in memory
        from PyQt6.QtGui import QPainter, QColor, QPen
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(0, 229, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(2, 2, 28, 28, 6, 6)
        
        # Draw a small mathematical symbol "f(x)" or sign
        painter.setPen(QPen(QColor(14, 14, 18), 3))
        painter.drawLine(8, 16, 24, 16) # Minus / Division line
        painter.drawLine(16, 8, 16, 24) # Plus sign
        painter.end()
        
        self.tray_icon.setIcon(QIcon(pixmap))
        
        # Tray Menu
        menu = QMenu()
        
        action_snip = QAction("Recortar Fórmula (Ctrl+Alt+S)", menu)
        action_snip.triggered.connect(self.activate_snipping)
        menu.addAction(action_snip)
        
        menu.addSeparator()
        
        action_exit = QAction("Salir", menu)
        action_exit.triggered.connect(self.exit_app)
        menu.addAction(action_exit)
        
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

    def status_tray_message(self, title, text):
        self.tray_icon.showMessage(
            title,
            text,
            QSystemTrayIcon.MessageIcon.Information,
            3000
        )

    def on_model_loaded(self, success):
        if success:
            self.status_tray_message(
                "¡MathOCR Listo!", 
                "Presiona Ctrl + Alt + S en cualquier lugar para recortar una fórmula matemática."
            )
        else:
            QMessageBox.critical(
                None, 
                "Error en Motor OCR", 
                "No se pudo cargar el motor local de OCR. Por favor comprueba tus dependencias."
            )

    def setup_hotkey(self):
        # We listen to Ctrl + Alt + S
        # Using pynput GlobalHotKeys is robust and cross-platform
        def trigger():
            self.signaler.trigger_snipper.emit()

        # Register the hotkey
        self.listener = keyboard.GlobalHotKeys({
            '<ctrl>+<alt>+s': trigger
        })
        self.listener.start()

    def activate_snipping(self):
        if not self.ocr_engine.initialized:
            self.status_tray_message(
                "MathOCR", 
                "Esperando a que termine de cargar el motor de OCR..."
            )
            return
        self.snipper.start_capture()

    def process_snip(self, image_path):
        self.status_tray_message("MathOCR", "Procesando recorte matemático...")
        
        # Stop any running worker
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
            
        self.worker = OCRWorker(image_path, self.ocr_engine)
        self.worker.finished.connect(self.on_ocr_finished)
        self.worker.error.connect(self.on_ocr_error)
        self.worker.start()

    def on_ocr_finished(self, latex, text, elapse_time):
        self.results_window.display_result(latex, text, elapse_time)
        self.status_tray_message("¡Completado!", "El resultado ha sido copiado al portapapeles.")

    def on_ocr_error(self, err_msg):
        QMessageBox.critical(
            None,
            "Error de Procesamiento",
            f"Ocurrió un error al procesar el recorte:\n{err_msg}"
        )

    def exit_app(self):
        if self.listener:
            self.listener.stop()
        self.app.quit()

    def run(self):
        return self.app.exec()


def main():
    app = MathOCRApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
