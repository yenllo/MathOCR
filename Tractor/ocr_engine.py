import os
import sys
import warnings
warnings.filterwarnings("ignore")
import traceback
import re

def cleanup_mixed_text(text):
    if not text:
        return text
        
    # 0. Limpiar alucinaciones de caracteres asiáticos (común en diagramas de Venn/Logos)
    text = re.sub(r'[\u4e00-\u9fff]+', '', text)
        
    # 1. Corregir errores ortográficos comunes de letras en español producidos por el OCR
    replacements = {
        r'\butiliando\b': 'utilizando',
        r'\bUtiliando\b': 'Utilizando',
        r'\bnimero\b': 'número',
        r'\bNimero\b': 'Número',
        r'\bnimeros\b': 'números',
        r'\bNimeros\b': 'Números',
        r'\bformula\b': 'fórmula',
        r'\bFormula\b': 'Fórmula',
    }
    
    for pattern, repl in replacements.items():
        text = re.sub(pattern, repl, text)
        
    # 2. Corregir la conjunción "y" cuando queda atrapada en negrita matemática al final de un bloque inline
    # Ejemplo: ...\mathbb{N} \textbf{y}$ o \mathbf{y}$ -> ...\mathbb{N}$ y
    text = re.sub(r'\\(?:textbf|mathbf)\{\s*y\s*\}\s*\$', '$ y', text)
    
    # 3. Corregir la conjunción "y" si queda en negrita en otros lados del texto plano (ej. \textbf{y} o \mathbf{y})
    text = re.sub(r'\\(?:textbf|mathbf)\{\s*y\s*\}', ' y ', text)
    
    # 4. Corregir la conjunción "y" cuando queda como un bloque matemático completo solitario (ej. $\mathbf{y}$)
    text = re.sub(r'\$\s*\\(?:textbf|mathbf)\{\s*y\s*\}\s*\$', ' y ', text)
    
    # 5. Corregir corchetes de puntos que se confunden con barras verticales (ej. |3 ptos.] -> [3 ptos.])
    text = re.sub(r'\|\s*(\d+)\s*ptos\.?\]', r'[\1 ptos.]', text)
    
    # 6. Limpiar espacios duplicados o triples
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

class OCREngine:
    def __init__(self):
        self.p2t = None
        self.initialized = False

    def initialize(self):
        """Inicializa Pix2Text (OCR Mixto) con DirectML."""
        if self.initialized:
            return True
        try:
            # ─── Supresión de Auto-Instaladores y Optimización ONNX ─────
            os.environ["ORT_DEFAULT_PROVIDERS"] = "DmlExecutionProvider"
            os.environ["ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS"] = "1"
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
            
            # Inicializar el motor de OCR mixto Pix2Text.
            # languages=('en','es'): el material es español. Esto (a) cambia el OCR
            # de texto a EasyOCR (alfabeto latino → respeta acentos á/é/í/ó/ú/ñ) y
            # (b) activa el corrector ortográfico español integrado (diccionario,
            # no LLM). Las fórmulas (MFD/MFR) no se ven afectadas.
            from pix2text import Pix2Text
            self.p2t = Pix2Text.from_config(
                total_configs={'text_formula': {'languages': ('en', 'es')}},
                device='cpu',
            )
            
            # Inyectar DirectML a nivel de instancia (Setter Injection)
            self._inject_directml()
            
            self.initialized = True
            return True
        except Exception as e:
            import traceback
            error_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_init_error.log")
            try:
                with open(error_log_path, "w", encoding="utf-8") as f:
                    f.write("Error al inicializar el motor Tractor OCR:\n")
                    f.write(f"Exception: {e}\n\n")
                    traceback.print_exc(file=f)
            except Exception as write_err:
                print(f"No se pudo escribir el log de error: {write_err}")
            print(f"Error al inicializar el motor Tractor OCR: {e}")
            return False

    def _inject_directml(self):
        """Reemplaza sesiones ONNX con DmlExecutionProvider."""
        import onnxruntime as ort
        
        # Verificar que DirectML esté disponible
        available_providers = ort.get_available_providers()
        if "DmlExecutionProvider" not in available_providers:
            print("Advertencia: DmlExecutionProvider no disponible en ONNX Runtime.")
            return

        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        
        def reinit_session(old_session_wrapper):
            if not hasattr(old_session_wrapper, 'session') or old_session_wrapper.session is None:
                return
            
            old_sess = old_session_wrapper.session
            model_path = getattr(old_sess, '_model_path', None)
                
            if model_path:
                try:
                    sess_opt = ort.SessionOptions()
                    sess_opt.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                    new_sess = ort.InferenceSession(str(model_path), sess_options=sess_opt, providers=providers)
                    old_session_wrapper.session = new_sess
                    print(f"[DirectML] Aceleración inyectada en: {os.path.basename(model_path)}")
                except Exception as e:
                    print(f"Fallo al inyectar DirectML en {model_path}: {e}")

        def inject_recursive(obj, depth=0):
            if depth > 4 or obj is None: return
            if hasattr(obj, 'session') and isinstance(getattr(obj, 'session'), ort.InferenceSession):
                reinit_session(obj)
                return
            if hasattr(obj, 'model'):
                inject_recursive(obj.model, depth+1)
            if hasattr(obj, 'postprocess_op'):
                inject_recursive(obj.postprocess_op, depth+1)
            if hasattr(obj, 'text_formula_ocr'):
                inject_recursive(obj.text_formula_ocr, depth+1)
            if hasattr(obj, 'text_ocr'):
                inject_recursive(obj.text_ocr, depth+1)
            if hasattr(obj, 'mfd'):
                inject_recursive(obj.mfd, depth+1)

        if self.p2t:
            inject_recursive(self.p2t)

    def recognize_page(self, pil_image):
        """Procesa una página completa usando Pix2Text (Motor 2)."""
        if not self.initialized:
            self.initialize()
        if self.p2t is None:
            raise RuntimeError("El motor Pix2Text no pudo inicializarse.")
        try:
            result = self.p2t.recognize(pil_image)
            return cleanup_mixed_text(result)
        except Exception as e:
            return f"[Error OCR en esta página: {e}]"
