import os
from PyQt6.QtCore import Qt, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QPixmap, QKeySequence, QShortcut
from PyQt6.QtWidgets import QWidget, QApplication

class SnipperWindow(QWidget):
    # Signals
    snipped = pyqtSignal(str)  # Emits the path to the saved temporary image file
    closed = pyqtSignal()      # Emits when snipper is closed without selection

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Window flags to make it borderless, cover the whole screen, and stay on top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        
        # Semi-transparent background
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.begin = QPoint()
        self.end = QPoint()
        self.is_drawing = False
        
        # Premium Styling Colors
        self.overlay_color = QColor(10, 10, 15, 160)    # Sleek dark semi-transparent overlay
        self.selection_color = QColor(0, 229, 255)      # Cyan border
        self.fill_color = QColor(0, 229, 255, 20)       # Ultra-subtle cyan fill
        
        # Shortcut to close with Escape
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_shortcut.activated.connect(self.close_without_snip)
        
        self.temp_img_path = os.path.join(os.environ.get("TEMP", "."), "temp_snip.png")
        self.screen_captures = []

    def start_capture(self):
        # Clear previous captures
        self.screen_captures = []
        
        # Hide the snipper window first to make sure it's not captured
        self.hide()
        
        # Process events so the window is completely hidden from the desktop
        QApplication.processEvents()
        
        # Determine geometry covering all screens combined
        screens = QApplication.screens()
        left = 0
        top = 0
        right = 0
        bottom = 0
        for screen in screens:
            geom = screen.geometry()
            left = min(left, geom.x())
            top = min(top, geom.y())
            right = max(right, geom.x() + geom.width())
            bottom = max(bottom, geom.y() + geom.height())
            
            # Grab screenshot of this screen natively
            pixmap = screen.grabWindow(0)
            self.screen_captures.append((geom, pixmap))
            
        self.setGeometry(QRect(left, top, right - left, bottom - top))
        
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        QApplication.setOverrideCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw background screens (natively scaled by QPainter)
        for geom, pixmap in self.screen_captures:
            painter.drawPixmap(geom.topLeft(), pixmap)
            
        # Draw semi-transparent dark overlay
        painter.fillRect(self.rect(), self.overlay_color)
        
        if self.is_drawing:
            # Calculate the current selection rectangle
            rect = QRect(self.begin, self.end).normalized()
            
            # Clear overlay inside selection (show original screens sharply)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            
            # Restore default composition to draw the neon selection border
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            
            # Draw premium neon cyan border and subtle inner fill
            pen = QPen(self.selection_color, 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(self.fill_color))
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.begin = event.position().toPoint()
            self.end = self.begin
            self.is_drawing = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_drawing:
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_drawing:
            self.is_drawing = False
            QApplication.restoreOverrideCursor()
            self.hide()
            
            rect = QRect(self.begin, self.end).normalized()
            
            # Check if selection is large enough
            if rect.width() > 5 and rect.height() > 5:
                # Determine active screen's DPR based on selection center
                center = rect.center()
                active_screen = QApplication.primaryScreen()
                for screen in QApplication.screens():
                    if screen.geometry().contains(center):
                        active_screen = screen
                        break
                
                dpr = active_screen.devicePixelRatio()
                physical_w = int(rect.width() * dpr)
                physical_h = int(rect.height() * dpr)
                
                # Create a high-DPI canvas
                cropped = QPixmap(physical_w, physical_h)
                cropped.setDevicePixelRatio(dpr)
                
                # Paint the screenshots onto the cropped region
                painter = QPainter(cropped)
                painter.translate(-rect.x(), -rect.y())
                for geom, pixmap in self.screen_captures:
                    painter.drawPixmap(geom.topLeft(), pixmap)
                painter.end()
                
                # Save physical pixels to file
                cropped.save(self.temp_img_path, "PNG")
                self.snipped.emit(self.temp_img_path)
            else:
                self.close_without_snip()

    def close_without_snip(self):
        QApplication.restoreOverrideCursor()
        self.hide()
        self.closed.emit()

