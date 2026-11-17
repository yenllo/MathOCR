import os
import sys
import warnings
warnings.filterwarnings("ignore")
import traceback
import re
from PyQt6.QtCore import QThread, pyqtSignal

def cleanup_latex(latex_str):
    # Remove redundant whitespace
    latex_str = re.sub(r'\s+', ' ', latex_str).strip()
    
    # Simplify double braces around single letters/symbols, e.g., {{z}} -> {z}
    for _ in range(3):
        latex_str = re.compile(r'\{\{([^{}]+)\}\}').sub(r'{\1}', latex_str)
        
    # Simplify single character braces in standard macros, e.g., \overline{{z}} -> \overline{z}
    latex_str = re.sub(r'\\(bar|overline|hat|tilde|vec)\{\{([^{}]+)\}\}', r'\\\1{\2}', latex_str)
    
    # Convert \overline{<single letter>} to \bar{<single letter>} for a cleaner math representation
    latex_str = re.sub(r'\\overline\{([a-zA-Z])\}', r'\\bar{\1}', latex_str)
    
    # Remove redundant braces around single characters inside operations, e.g. +{z} -> +z, -{z} -> -z, ={z} -> =z
    latex_str = re.sub(r'([+\-=])\{([a-zA-Z])\}', r'\1\2', latex_str)
    
    # Convert \stackrel{<index>}{\sqrt{<content>}} to proper LaTeX root \sqrt[<index>]{<content>}
    def fix_root_index(idx):
        idx = idx.strip()
        if idx in (r'\vartheta', r'\theta'):
            return '8'
        return idx

    latex_str = re.sub(
        r'\\stackrel\{([^{}]+)\}\{\\sqrt\s*\{?([^{}]+)\}?\}',
        lambda m: f"\\sqrt[{fix_root_index(m.group(1))}]{m.group(2)}",
        latex_str
    )
    
    # Map common OCR errors inside any standard \sqrt[index] (e.g. \sqrt[\vartheta] -> \sqrt[8])
    latex_str = re.sub(r'\\sqrt\[\s*\\(?:vartheta|theta)\s*\]', r'\\sqrt[8]', latex_str)
    
    # Remove outer braces enclosing the whole string if they are redundant
    if latex_str.startswith('{') and latex_str.endswith('}'):
        depth = 0
        matching = True
        for i, char in enumerate(latex_str):
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and i < len(latex_str) - 1:
                     matching = False
                     break
        if matching:
            latex_str = latex_str[1:-1]
            
    return latex_str

def cleanup_mixed_text(text):
    return text

class OCRWorker(QThread):
    finished = pyqtSignal(str, str, float)  # Emits (latex_result, text_result, time_elapsed)
    error = pyqtSignal(str)                 # Emits error message

    def __init__(self, image_path, ocr_engine=None):
        super().__init__()
        self.image_path = image_path
        self.ocr_engine = ocr_engine

    def run(self):
        try:
            if self.ocr_engine is None or self.ocr_engine.model is None:
                self.error.emit("El motor OCR no está inicializado.")
                return
            
            from PIL import Image, ImageOps
            import numpy as np
            
            img = Image.open(self.image_path).convert('RGB')
            img_array = np.array(img)
            
            # Evitar división por cero si la imagen es un color sólido
            if img_array.min() == img_array.max():
                self.error.emit("El recorte está completamente vacío o es de un solo color sólido. Por favor, selecciona la fórmula correctamente.")
                return
                
            gray = img.convert('L')
            avg_brightness = np.mean(np.array(gray))
            
            # Invertir colores si el fondo es oscuro (Modo Oscuro)
            if avg_brightness < 127:
                img = ImageOps.invert(img)
                
            # Guardamos la versión procesada en disco
            processed_path = self.image_path + "_proc.png"
            img.save(processed_path)

            # Inferencia
            import time
            start_time = time.time()
            
            # 1. Inferencia de Fórmula pura usando rapid_latex_ocr (Corrección DirectML: corre en CPUExecutionProvider por defecto)
            result_tuple = self.ocr_engine.model(np.array(img))
            latex_str = result_tuple[0]
            
            # 2. Inferencia Mixta (No disponible en app simple)
            mixed_markdown = "OCR Mixto no disponible en la aplicación simple. Use el Tractor para procesar PDFs de texto mixto."
                
            elapse = time.time() - start_time
            
            # Extraer cadena LaTeX
            if not latex_str:
                latex_str = ""
            else:
                latex_str = str(latex_str)
                
            # Limpiar llaves dobles o macros redundantes
            cleaned_latex = cleanup_latex(latex_str)
                
            self.finished.emit(cleaned_latex, mixed_markdown, elapse)
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            self.error.emit(err_msg)

class OCREngine:
    def __init__(self):
        self.model = None
        self.p2t = None  # None en SimpleApp
        self.initialized = False

    def initialize(self):
        """Inicializa rapid_latex_ocr (Matemática pura)."""
        if self.initialized:
            return True
        try:
            # Apagar librería espía (Wandb)
            os.environ["WANDB_MODE"] = "disabled"
            os.environ["WANDB_DISABLED"] = "true"
            
            # Solución para pythonw.exe
            if sys.stdout is None:
                class DummyWriter:
                    encoding = 'utf-8'
                    def write(self, *args, **kwargs): pass
                    def flush(self): pass
                sys.stdout = DummyWriter()
            if sys.stderr is None:
                class DummyWriter:
                    encoding = 'utf-8'
                    def write(self, *args, **kwargs): pass
                    def flush(self): pass
                sys.stderr = DummyWriter()
            
            # Inicializar el motor matemático rapid_latex_ocr
            from rapid_latex_ocr.main import LaTeXOCR
            self.model = LaTeXOCR()
            
            self.initialized = True
            return True
        except Exception as e:
            import traceback
            error_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_init_error.log")
            try:
                with open(error_log_path, "w", encoding="utf-8") as f:
                    f.write("Error al inicializar el motor Simple OCR:\n")
                    f.write(f"Exception: {e}\n\n")
                    traceback.print_exc(file=f)
            except Exception as write_err:
                print(f"No se pudo escribir el log de error: {write_err}")
            print(f"Error al inicializar el motor Simple OCR: {e}")
            return False

    def recognize(self, image_path):
        if not self.initialized:
            self.initialize()
        if self.model:
            import numpy as np
            from PIL import Image
            img = Image.open(image_path).convert('RGB')
            res, _ = self.model(np.array(img))
            return res
        raise RuntimeError("El motor de OCR rapid_latex_ocr no pudo inicializarse.")
