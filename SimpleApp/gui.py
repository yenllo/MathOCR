import sys
import os
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap, QClipboard, QImage
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, 
    QPushButton, QMessageBox, QFrame, QApplication, QSplitter,
    QTabWidget
)
import pyperclip
import matplotlib
matplotlib.use('Agg')

class ResultsWindow(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MathOCR - Resultados del Recorte")
        self.resize(650, 520)
        self.setMinimumSize(500, 450)
        
        # Premium dark styling with neon cian accents
        self.setStyleSheet("""
            QWidget {
                background-color: #0E0E12;
                color: #E2E2E9;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, sans-serif;
            }
            QFrame#card {
                background-color: #161622;
                border: 1px solid #2A2A3C;
                border-radius: 12px;
            }
            QLabel {
                font-size: 13px;
            }
            QLabel#title {
                font-size: 18px;
                font-weight: bold;
                color: #00E5FF;
            }
            QLabel#preview_label {
                background-color: #1F1F30;
                border: 1px dashed #3F3F5C;
                border-radius: 8px;
                padding: 10px;
                qproperty-alignment: AlignCenter;
            }
            QTextEdit {
                background-color: #1B1B2A;
                border: 1px solid #2E2E44;
                border-radius: 8px;
                color: #F0F0F5;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 14px;
                padding: 8px;
            }
            QTextEdit:focus {
                border: 1px solid #00E5FF;
            }
            QPushButton {
                background-color: #00E5FF;
                color: #0E0E12;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #33EBFF;
            }
            QPushButton:pressed {
                background-color: #00B2C4;
            }
            QPushButton#secondary_btn {
                background-color: #242438;
                color: #E2E2E9;
                border: 1px solid #3F3F5C;
            }
            QPushButton#secondary_btn:hover {
                background-color: #2E2E48;
                border-color: #00E5FF;
            }
            QLabel#status {
                color: #8E8E9F;
                font-size: 11px;
            }
            
            /* Modern TabWidget styling */
            QTabWidget::pane {
                border: 1px solid #2A2A3C;
                border-radius: 8px;
                background-color: #161622;
                position: absolute;
                top: -1px;
            }
            QTabBar::tab {
                background-color: #14141F;
                color: #8E8E9F;
                border: 1px solid #2A2A3C;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #161622;
                color: #00E5FF;
                border-bottom: 2px solid #00E5FF;
                border-color: #2A2A3C;
                border-bottom-color: #161622;
            }
            QTabBar::tab:hover {
                color: #00E5FF;
                background-color: #1C1C2D;
            }
        """)
        
        self.latex_str = ""
        self.text_str = ""
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)
        
        # Header / Title Bar
        header = QHBoxLayout()
        title_label = QLabel("MathOCR - Análisis Completado")
        title_label.setObjectName("title")
        header.addWidget(title_label)
        
        header.addStretch()
        
        self.status_label = QLabel("Listo")
        self.status_label.setObjectName("status")
        header.addWidget(self.status_label)
        main_layout.addLayout(header)
        
        # Tabs widget
        self.tabs = QTabWidget()
        
        # Tab 1: Math Formula
        self.tab_math = QWidget()
        math_layout = QVBoxLayout(self.tab_math)
        math_layout.setContentsMargins(12, 12, 12, 12)
        math_layout.setSpacing(10)
        
        preview_title = QLabel("Previsualización de Fórmula:")
        preview_title.setStyleSheet("font-weight: bold; color: #8E8E9F;")
        math_layout.addWidget(preview_title)
        
        self.preview_area = QLabel("La previsualización matemática aparecerá aquí")
        self.preview_area.setObjectName("preview_label")
        self.preview_area.setMinimumHeight(110)
        math_layout.addWidget(self.preview_area)
        
        latex_title = QLabel("Código LaTeX (Editable):")
        latex_title.setStyleSheet("font-weight: bold; color: #8E8E9F;")
        math_layout.addWidget(latex_title)
        
        self.latex_edit = QTextEdit()
        self.latex_edit.setPlaceholderText("Esperando recorte matemático...")
        self.latex_edit.textChanged.connect(self.on_latex_changed)
        math_layout.addWidget(self.latex_edit)
        
        self.tabs.addTab(self.tab_math, "🧮 Fórmula LaTeX")
        
        # Tab 2: Plain Text
        self.tab_text = QWidget()
        text_layout = QVBoxLayout(self.tab_text)
        text_layout.setContentsMargins(12, 12, 12, 12)
        text_layout.setSpacing(10)
        
        text_title = QLabel("Texto y Ecuaciones Integradas (Markdown + LaTeX):")
        text_title.setStyleSheet("font-weight: bold; color: #8E8E9F;")
        text_layout.addWidget(text_title)
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Esperando recorte mixto (Texto + Fórmulas)...")
        self.text_edit.textChanged.connect(self.on_text_changed)
        text_layout.addWidget(self.text_edit)
        
        # Tab action for text
        self.btn_copy_text_tab = QPushButton("Copiar Texto + LaTeX")
        self.btn_copy_text_tab.clicked.connect(self.copy_text)
        text_layout.addWidget(self.btn_copy_text_tab)
        
        self.tabs.addTab(self.tab_text, "📝 Texto + LaTeX")
        
        main_layout.addWidget(self.tabs)
        
        # Actions Area (Universal bottom actions)
        actions_layout = QHBoxLayout()
        
        self.btn_copy_latex = QPushButton("Copiar LaTeX")
        self.btn_copy_latex.clicked.connect(self.copy_latex)
        actions_layout.addWidget(self.btn_copy_latex)
        
        self.btn_copy_md = QPushButton("Copiar para Markdown ($$)")
        self.btn_copy_md.setObjectName("secondary_btn")
        self.btn_copy_md.clicked.connect(self.copy_markdown)
        actions_layout.addWidget(self.btn_copy_md)
        
        self.btn_close = QPushButton("Cerrar")
        self.btn_close.setObjectName("secondary_btn")
        self.btn_close.clicked.connect(self.close)
        actions_layout.addWidget(self.btn_close)
        
        main_layout.addLayout(actions_layout)

    def display_result(self, latex, text, elapse_time):
        self.latex_str = latex
        self.text_str = text
        
        # Block signals temporarily to prevent infinite loop
        self.latex_edit.blockSignals(True)
        self.latex_edit.setText(latex)
        self.latex_edit.blockSignals(False)
        
        self.text_edit.blockSignals(True)
        self.text_edit.setText(text)
        self.text_edit.blockSignals(False)
        
        self.status_label.setText(f"Procesado en {elapse_time:.2f}s")
        self.update_preview(latex)
        
        # Inteligencia de Pestañas: 
        # Si el resultado de LaTeX está vacío o contiene cadenas de alucinación de texto muy evidentes,
        # o si el texto plano es significativamente más rico y estructurado que el código LaTeX devuelto,
        # seleccionamos la pestaña de texto por defecto. De lo contrario, priorizamos la pestaña matemática.
        has_rich_text = len(text.strip()) > 10
        has_garbage_latex = "\\mathrm{" in latex and len(latex) > 100
        
        if has_rich_text and (not latex.strip() or has_garbage_latex):
            self.tabs.setCurrentIndex(1) # Pestaña de Texto Detectado
            pyperclip.copy(text)
        else:
            self.tabs.setCurrentIndex(0) # Pestaña de Fórmula LaTeX
            pyperclip.copy(latex)
            
        self.show()
        self.raise_()
        self.activateWindow()

    def on_latex_changed(self):
        new_latex = self.latex_edit.toPlainText()
        self.latex_str = new_latex
        self.update_preview(new_latex)

    def on_text_changed(self):
        self.text_str = self.text_edit.toPlainText()

    def update_preview(self, latex):
        if not latex.strip():
            self.preview_area.setText("Escribe o recorta una fórmula...")
            return
            
        try:
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            
            # Setup a clean figure to render the math equation
            fig = plt.figure(figsize=(6, 2), dpi=100, facecolor='#1F1F30')
            fig.text(0.5, 0.5, f"${latex}$", 
                     horizontalalignment='center', 
                     verticalalignment='center',
                     fontsize=16, 
                     color='#E2E2E9')
            
            # Use Agg renderer to render to canvas
            canvas = FigureCanvasAgg(fig)
            canvas.draw()
            
            # Convert canvas output to QPixmap
            width, height = fig.get_size_inches() * fig.get_dpi()
            width, height = int(width), int(height)
            
            img_data = canvas.buffer_rgba()
            qimg = QPixmap.fromImage(
                QImage(
                    img_data, width, height, QImage.Format.Format_RGBA8888
                )
            )
            
            # Scale dynamically to fit the area
            self.preview_area.setPixmap(qimg.scaled(
                self.preview_area.width() - 20, 
                self.preview_area.height() - 20, 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            ))
            plt.close(fig)
        except Exception as e:
            self.preview_area.setText(f"[Vista Previa no disponible]")
            print(f"Error rendering preview: {e}")

    def copy_latex(self):
        pyperclip.copy(self.latex_str)
        self.status_label.setText("¡LaTeX copiado al portapapeles!")

    def copy_markdown(self):
        md_format = f"$${self.latex_str}$$"
        pyperclip.copy(md_format)
        self.status_label.setText("¡Formato Markdown copiado!")

    def copy_text(self):
        pyperclip.copy(self.text_str)
        self.status_label.setText("¡Texto plano copiado!")

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()
