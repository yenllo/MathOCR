#!/usr/bin/env python
"""🚜 MathOCR Batch Processor — Convierte carpetas de PDFs a Markdown con LaTeX."""

# ─── Standard Library ─────────────────────────────────────
import argparse
import gc
import io
import logging
import os
import sys
import time
import warnings
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import unquote_plus

# ─── Suprimir warnings antes de imports pesados ───────────
warnings.filterwarnings("ignore")

# ─── Bootstrap de sys.path ────────────────────────────────
# Garantiza que los imports desnudos (ocr_engine, llm_cleaner, format_cleaner)
# resuelvan a esta carpeta sin importar el cwd. También cubre los subprocesos
# spawn de Windows (ProcessPoolExecutor), que vuelven a ejecutar este módulo.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ─── Dependencias Pesadas ─────────────────────────────────
import fitz                      # PyMuPDF — renderizado de PDFs
from PIL import Image            # Pillow — manipulación de imágenes
from tqdm import tqdm as original_tqdm
import tqdm as tqdm_module

# ─── Silenciador Global de tqdm (Terceros) ────────────────
class SilentTqdm(original_tqdm):
    def __init__(self, *args, **kwargs):
        kwargs['disable'] = True
        super().__init__(*args, **kwargs)
tqdm_module.tqdm = SilentTqdm

# ─── Módulos Locales ──────────────────────────────────────
from ocr_engine import OCREngine, cleanup_mixed_text


@contextmanager
def suppress_stdout_stderr():
    """Silencia stdout, stderr y logs de PyTorch/ultralytics durante la inicialización OCR."""
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    devnull = open(os.devnull, 'w')
    sys.stdout = devnull
    sys.stderr = devnull
    
    loggers_to_silence = [
        'ultralytics',
        'doclayout_yolo', 
        'pix2text',
        'torch',
        'torchvision',
    ]
    original_levels = {}
    for logger_name in loggers_to_silence:
        logger = logging.getLogger(logger_name)
        original_levels[logger_name] = logger.level
        logger.setLevel(logging.ERROR)
    
    try:
        yield
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        # No cerramos devnull porque librerías espía como WANDB / Colorama pueden haber 
        # guardado una referencia a este stream y fallarán con 'I/O on closed file'.
        # devnull.close() 
        for logger_name, level in original_levels.items():
            logging.getLogger(logger_name).setLevel(level)


def discover_pdfs(input_path):
    """Retorna lista de rutas absolutas a todos los .pdf encontrados recursivamente."""
    input_path = os.path.abspath(input_path)
    
    # Caso: archivo individual
    if os.path.isfile(input_path):
        if not input_path.lower().endswith(".pdf"):
            raise ValueError("El archivo proporcionado no es un PDF válido.")
        return [input_path]
    
    # Caso: directorio (escaneo recursivo)
    pdfs = []
    for root, dirs, files in os.walk(input_path):
        dirs[:] = [d for d in dirs if d != "__MACOSX"]   # metadatos de zips de macOS, no PDFs
        for f in sorted(files):
            if f.lower().endswith(".pdf") and not f.startswith("._"):
                pdfs.append(os.path.join(root, f))
    return pdfs


def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes} min {secs}s"


def format_size(bytes_size):
    kb = bytes_size / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    return f"{mb:.1f} MB"


def _frontmatter(filename, source_rel, total_pages, alertas):
    """YAML del .md. `source_path` (relativo a la carpeta de entrada, con el nombre
    real en disco) y `alertas` (páginas a verificar contra el PDF) son para que
    quien lea el .md sepa qué página del original abrir."""
    lineas = ["---", "tags:", "  - auto-ocr", "  - tractor",
              f"source: \"{filename}\""]
    if source_rel:
        lineas.append(f"source_path: \"{source_rel.replace(os.sep, '/')}\"")
    lineas += [f"processed_date: \"{datetime.now().strftime('%Y-%m-%d')}\"",
               f"pages: {total_pages}"]
    if any(alertas.values()):
        lineas.append("alertas:")
        lineas += [f"  {k}: {v}" for k, v in alertas.items() if v]
    return "\n".join(lineas) + "\n---\n\n"


def process_single_pdf(pdf_path, output_path, engine, dpi=150, cooldown=2.5, strip_junk=True, clean=False, clean_llm_model=None, quiet=False, progress_queue=None, source_rel=None):
    """
    Procesa un solo PDF. Escribe en un archivo temporal .tmp y solo al terminar
    con éxito hace rename al archivo .md destino.
    """
    tmp_output_path = output_path + ".tmp"
    start_time = time.time()

    try:
        # Abrir el PDF
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        # Páginas a verificar contra el PDF: solo_imagen (sin texto, p. ej. una
        # foto en una lámina) y ocr_completo (escaneada/manuscrita o fallback).
        alertas = {"solo_imagen": [], "manuscrita": [], "ocr_completo": []}

        # El cuerpo va al .tmp; el frontmatter se antepone al final, cuando ya
        # se conocen las alertas.
        with open(tmp_output_path, "w", encoding="utf-8") as f:
            # Canvas entrega los PDFs con el nombre URL-encoded ("Inducci%C3%B3n+...").
            filename = unquote_plus(os.path.basename(pdf_path))

            # Nombre del documento como título principal
            # Solo la inicial: .title() destrozaba siglas ("EPP" -> "Epp").
            title = os.path.splitext(filename)[0].replace("_", " ")
            title = title[:1].upper() + title[1:]
            f.write(f"# {title}\n\n")
            
            # Procesar cada página
            with original_tqdm(total=total_pages, desc="  Procesando páginas", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]", leave=False, disable=quiet) as pbar:
                for i in range(total_pages):
                    page = doc[i]
                    f.write(f"## Página {i+1}\n\n")
                    
                    # 1. Renderizar a imagen con PyMuPDF
                    pix = page.get_pixmap(dpi=dpi)
                    
                    # 2. Convertir a PIL Image
                    img_data = pix.tobytes("png")
                    pil_img = Image.open(io.BytesIO(img_data)).convert('RGB')
                    
                    # 3. Extracción: híbrida para páginas DIGITALES (prosa/tablas
                    #    nativas + fórmulas OCR), OCR completo para escaneadas.
                    from native_extractor import is_digital, extract_page_hybrid, es_manuscrita
                    markdown_content = None
                    if es_manuscrita(page):
                        alertas["manuscrita"].append(i + 1)
                        f.write("_[Página manuscrita: el texto es reconocimiento automático "
                                "de escritura; verificar en el PDF]_\n\n")
                    if is_digital(page):
                        try:
                            markdown_content = extract_page_hybrid(page, pil_img, engine, dpi, strip_junk)
                        except Exception:
                            markdown_content = None  # fallback a OCR completo
                    if not markdown_content:
                        markdown_content = engine.recognize_page(pil_img)
                        alertas["ocr_completo"].append(i + 1)

                    # 3.1. Filtro anti-alucinación (ON por defecto; --raw lo apaga).
                    #   Descarta blobs basura de gráficos decorativos; no toca matemática real.
                    if markdown_content and strip_junk:
                        from hallucination_filter import strip_hallucinations
                        markdown_content = strip_hallucinations(markdown_content)

                    # 3.5. Limpieza opcional de SOLO FORMATO (nunca contenido matemático).
                    #   --clean      -> pasada determinista (regex), no puede alucinar.
                    #   --clean-llm  -> pasada extra con LLM (prompt restringido a formato).
                    if markdown_content and clean:
                        from format_cleaner import clean_format
                        markdown_content = clean_format(markdown_content)
                    if markdown_content and clean_llm_model:
                        from llm_cleaner import clean_text_with_ollama
                        markdown_content = clean_text_with_ollama(markdown_content, model_name=clean_llm_model)

                    if markdown_content and markdown_content.strip():
                        f.write(markdown_content + "\n\n")
                    elif page.get_images():
                        # Página sin texto: casi siempre una foto/ilustración. Se
                        # marca para que no parezca contenido perdido por el OCR.
                        f.write("_[Página sin texto: solo imagen]_\n\n")
                        alertas["solo_imagen"].append(i + 1)
                        if i + 1 in alertas["ocr_completo"]:
                            alertas["ocr_completo"].remove(i + 1)
                    f.write("---\n\n")
                    f.flush()
                    
                    # 4. Limpieza y control térmico
                    del pix
                    del pil_img
                    gc.collect()
                    
                    pbar.update(1)
                    if progress_queue is not None:
                        progress_queue.put(1)
                    if 'global_pbar' in globals() and global_pbar is not None:
                        global_pbar.update(1)
                    
                    if i < total_pages - 1 and cooldown > 0:
                        time.sleep(cooldown)
                        
        doc.close()

        # Si llegamos hasta aquí sin excepciones, la conversión fue exitosa:
        # se escribe el .md final (frontmatter + cuerpo) y se borra el .tmp.
        with open(tmp_output_path, encoding="utf-8") as fin:
            cuerpo = fin.read()
        with open(output_path, "w", encoding="utf-8") as fout:
            fout.write(_frontmatter(filename, source_rel, total_pages, alertas) + cuerpo)
        os.remove(tmp_output_path)
        
        elapse = time.time() - start_time
        file_size = os.path.getsize(output_path)
        return True, total_pages, elapse, file_size, None
        
    except Exception as e:
        # Hubo un error, no renombramos el archivo .tmp
        elapse = time.time() - start_time
        return False, 0, elapse, 0, str(e)


# ─── Worker functions for multiprocessing ────────────────
_worker_engine = None

def init_worker():
    """Inicializa silenciosamente el motor OCR en cada proceso hijo y asegura soporte UTF-8."""
    if sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass
            
    # Desactivar COMPLETAMENTE tqdm en los subprocesos para silenciar librerías internas (Pix2Text, Hugging Face, etc.)
    import tqdm
    original_tqdm = tqdm.tqdm
    class SilentTqdm(original_tqdm):
        def __init__(self, *args, **kwargs):
            kwargs['disable'] = True
            super().__init__(*args, **kwargs)
    tqdm.tqdm = SilentTqdm
    
    # Evitar la sobresuscripción de CPU limitando PyTorch a 1 hilo por proceso hijo
    try:
        import torch
        torch.set_num_threads(1)
    except Exception:
        pass
            
    global _worker_engine
    if _worker_engine is None:
        from ocr_engine import OCREngine
        _worker_engine = OCREngine()
        with suppress_stdout_stderr():
            _worker_engine.initialize()

def worker_process_single(args_tuple):
    """Función de pasarela para el pool de procesos."""
    pdf_path, output_path, dpi, cooldown, strip_junk, clean, clean_llm_model, idx, total, quiet, progress_queue, source_rel = args_tuple
    init_worker()

    filename = os.path.basename(pdf_path)
    if not quiet:
        print(f"[START] [{idx}/{total}] procesando: {filename} ...")

    success, pages, elapse, size, error_msg = process_single_pdf(
        pdf_path, output_path, _worker_engine, dpi=dpi, cooldown=cooldown, strip_junk=strip_junk, clean=clean, clean_llm_model=clean_llm_model, quiet=quiet, progress_queue=progress_queue, source_rel=source_rel
    )
    
    if not quiet:
        if success:
            print(f"[SUCCESS] [{idx}/{total}] terminado: {filename} ({pages} págs, {elapse:.1f}s)")
        else:
            print(f"[ERROR] [{idx}/{total}] falló {filename}: {error_msg}")
        
    return success, pages, elapse, size, error_msg, pdf_path


def main():
    if sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(description="🚜 MathOCR Batch Processor — Convierte carpetas de PDFs a Markdown con LaTeX.")
    parser.add_argument("input_path", type=str, help="Carpeta con PDFs (escaneo recursivo) o archivo PDF individual")
    parser.add_argument("--out", "-o", type=str, default=None, help="Carpeta de salida para los .md (por defecto: '<entrada>_MD' junto a la entrada)")
    parser.add_argument("--dpi", type=int, default=150, help="Resolución de renderizado (100-300)")
    parser.add_argument("--cooldown", "-c", type=float, default=2.5, help="Pausa térmica entre páginas (segundos)")
    parser.add_argument("--force", action="store_true", help="Reprocesar PDFs que ya tienen .md generado")
    parser.add_argument("--raw", action="store_true", help="Salida CRUDA del motor: desactiva el filtro anti-alucinación (que por defecto descarta blobs basura de gráficos decorativos). No toca matemática real.")
    parser.add_argument("--clean", action="store_true", help="Limpieza determinista de SOLO formato (espaciado/símbolos) por regex. No usa LLM, no puede alucinar. Apagado por defecto.")
    parser.add_argument("--clean-llm", action="store_true", help="Pasada EXTRA con LLM (Ollama), restringida a formato. Opt-in explícito; nunca debe alterar contenido matemático.")
    parser.add_argument("--clean-model", type=str, default="phi3", help="Modelo de Ollama usado por --clean-llm (por defecto: 'phi3')")
    parser.add_argument("--workers", "-w", type=int, default=1, help="Número de procesos paralelos para procesar PDFs simultáneamente (por defecto: 1)")

    args = parser.parse_args()

    # El modelo LLM solo se usa si se pidió explícitamente --clean-llm.
    clean_llm_model = args.clean_model if args.clean_llm else None
    # Filtro anti-alucinación: ON salvo --raw.
    strip_junk = not args.raw
    
    # Nota: ya NO se fuerza workers=1 por DirectML. La inyección DirectML es
    # no-op contra pix2text 1.1.6 (todo corre en CPU), así que el paralelismo
    # por procesos es seguro y beneficioso (cada worker ~2GB RAM).

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  🚜 MathOCR Batch Processor v1.0                           ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")
    
    # 1. Normalización de rutas y descubrimiento
    input_dir = os.path.abspath(args.input_path)
    if os.path.isfile(input_dir):
        # Si es un solo archivo, su carpeta contenedora es el origen para relpath
        base_dir = os.path.dirname(input_dir)
    else:
        base_dir = input_dir

    # Salida: --out si se indicó; si no, '<entrada>_MD' junto a la entrada.
    if args.out:
        output_dir = os.path.abspath(args.out)
    else:
        output_dir = f"{os.path.normpath(base_dir)}_MD"
        
    print(f"  📁 Entrada:   {input_dir}")
    print(f"  📂 Salida:    {output_dir}")
    
    try:
        pdfs = discover_pdfs(input_dir)
    except Exception as e:
        print(f"  ❌ Error: {e}")
        sys.exit(1)
        
    total_pdfs = len(pdfs)
    print(f"  📄 PDFs:      {total_pdfs} archivos encontrados")
    clean_parts = []
    if args.clean:
        clean_parts.append("regex")
    if args.clean_llm:
        clean_parts.append(f"LLM:{args.clean_model}")
    clean_info = f"  |  🧼 Limpieza: {'+'.join(clean_parts)}" if clean_parts else ""
    filtro_info = "ON" if strip_junk else "OFF (--raw)"
    print(f"  🔧 DPI: {args.dpi}  |  ⏸ Pausa: {args.cooldown}s  |  🔄 Force: {'Sí' if args.force else 'No'}  |  🧹 Filtro: {filtro_info}{clean_info}  |  👥 Workers: {args.workers}\n")
    
    if total_pdfs == 0:
        print("  ⚠️ No se encontraron PDFs.")
        sys.exit(0)
        
    # Inicializar contadores y resultados
    processed_count = 0
    skipped_count = 0
    error_count = 0
    total_pages_processed = 0
    total_process_time = 0
    results = [] # Para el resumen final

    if args.workers > 1:
        # 🚀 MODO PARALELO (MULTIPROCESO)
        import multiprocessing
        manager = multiprocessing.Manager()
        progress_queue = manager.Queue()
        
        total_pages_to_process = 0
        tasks = []
        for idx, pdf_path in enumerate(pdfs, 1):
            rel_path = os.path.relpath(pdf_path, base_dir)
            md_rel_path = os.path.splitext(rel_path)[0] + ".md"
            output_path = os.path.join(output_dir, md_rel_path)
            
            if os.path.exists(output_path) and not args.force:
                print(f"  [SKIPPED] {rel_path} → ya existe {os.path.basename(output_path)}\n")
                skipped_count += 1
                results.append((rel_path, "skipped", 0, 0, md_rel_path))
                continue
                
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Obtener cantidad de páginas de forma ultra-rápida
            try:
                doc = fitz.open(pdf_path)
                total_pages_to_process += len(doc)
                doc.close()
            except Exception:
                pass
                
            tasks.append((pdf_path, output_path, args.dpi, args.cooldown, strip_junk, args.clean, clean_llm_model, idx, total_pdfs, True, progress_queue, rel_path))
            
        if tasks:
            print(f"  ⏳ Cargando pool de {args.workers} procesos paralelos...")
            from concurrent.futures import ProcessPoolExecutor
            
            # Usar pool
            start_pool_time = time.time()
            futures = []
            
            with ProcessPoolExecutor(max_workers=args.workers) as executor:
                # Lanzar todas las tareas al pool
                for t in tasks:
                    future = executor.submit(worker_process_single, t)
                    futures.append(future)
                
                # Barra de progreso única y global en tiempo real a nivel de PÁGINAS
                with original_tqdm(total=total_pages_to_process, desc="🚜 Progreso de Páginas", unit="pág", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]") as pbar:
                    completed_futures = set()
                    
                    while len(completed_futures) < len(futures) or not progress_queue.empty():
                        # 1. Vaciar la cola de progreso y actualizar barra
                        updates = 0
                        while not progress_queue.empty():
                            try:
                                progress_queue.get_nowait()
                                updates += 1
                            except Exception:
                                break
                        if updates > 0:
                            pbar.update(updates)
                            
                        # 2. Revisar si hay futuros completados para imprimir su reporte
                        for f in futures:
                            if f not in completed_futures and f.done():
                                completed_futures.add(f)
                                success, pages, elapse, size, error_msg, pdf_path = f.result()
                                rel_path = os.path.relpath(pdf_path, base_dir)
                                md_rel_path = os.path.splitext(rel_path)[0] + ".md"
                                filename = os.path.basename(pdf_path)
                                
                                if success:
                                    processed_count += 1
                                    total_pages_processed += pages
                                    total_process_time += elapse
                                    results.append((rel_path, "success", pages, size, md_rel_path))
                                    pbar.write(f"  ✅ [SUCCESS] {filename} ({pages} págs, {format_time(elapse)})")
                                else:
                                    error_count += 1
                                    results.append((rel_path, "error", 0, 0, md_rel_path))
                                    pbar.write(f"  ❌ [ERROR] {filename}: {error_msg}")
                                    
                        time.sleep(0.2)
                        
            print(f"\n  ✅ Procesamiento paralelo completado en {format_time(time.time() - start_pool_time)}\n")
    else:
        # 🚜 MODO SECUENCIAL CLÁSICO
        # 2. Inicializar motor OCR silenciosamente
        print("  ⏳ Cargando motor OCR...")
        load_start = time.time()
        
        engine = OCREngine()
        with suppress_stdout_stderr():
            success = engine.initialize()
            
        if not success:
            print("  ❌ Error: No se pudieron cargar los motores OCR.")
            sys.exit(1)
            
        print(f"  ✅ Motores cargados en {time.time() - load_start:.1f}s\n")
        
        # Pre-calcular páginas totales para la barra global
        total_pages_to_process = 0
        valid_pdfs = []
        print("  ⏳ Calculando lote total de páginas...")
        for pdf_path in pdfs:
            rel_path = os.path.relpath(pdf_path, base_dir)
            md_rel_path = os.path.splitext(rel_path)[0] + ".md"
            output_path = os.path.join(output_dir, md_rel_path)
            if os.path.exists(output_path) and not args.force:
                skipped_count += 1
                results.append((rel_path, "skipped", 0, 0, md_rel_path))
                continue
            try:
                doc = fitz.open(pdf_path)
                total_pages_to_process += len(doc)
                doc.close()
                valid_pdfs.append((pdf_path, rel_path, output_path, md_rel_path))
            except Exception:
                pass
                
        if total_pages_to_process > 0:
            print(f"  🎯 Total a procesar: {len(valid_pdfs)} PDFs ({total_pages_to_process} páginas)\n")
            global global_pbar
            global_pbar = original_tqdm(total=total_pages_to_process, desc="🚜 Progreso Global", unit="pág", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]")
            
            for pdf_path, rel_path, output_path, md_rel_path in valid_pdfs:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                
                # Imprimimos arriba de la barra de progreso usando pbar.write
                global_pbar.write(f"\n📄 {rel_path}")
                
                success, pages, elapse, size, error_msg = process_single_pdf(
                    pdf_path, output_path, engine, dpi=args.dpi, cooldown=args.cooldown, strip_junk=strip_junk, clean=args.clean, clean_llm_model=clean_llm_model, quiet=True, source_rel=rel_path
                )
                
                if success:
                    processed_count += 1
                    total_pages_processed += pages
                    total_process_time += elapse
                    results.append((rel_path, "success", pages, size, md_rel_path))
                else:
                    global_pbar.write(f"❌ Error al procesar {rel_path}: {error_msg}")
                    error_count += 1
                    results.append((rel_path, "error", 0, 0, md_rel_path))
            
            global_pbar.close()
            global_pbar = None
            
    # 4. Resumen Final
    print("══════════════════════════════════════════════════════════════")
    print("  🏁 RESUMEN FINAL")
    print("══════════════════════════════════════════════════════════════\n")
    
    print(f"  ✅ {processed_count}/{total_pdfs} PDFs procesados  |  ⏭ {skipped_count} saltados  |  ❌ {error_count} errores")
    if processed_count > 0:
        print(f"  📄 Total: {total_pages_processed} páginas en {format_time(total_process_time)}")
        if total_pages_processed > 0:
            speed = total_process_time / total_pages_processed
            print(f"  📊 Velocidad: {speed:.1f} s/pág\n")
            
    print("  Archivos generados:")
    for rel_path, status, pages, size, md_rel in results:
        if status == "success":
            print(f"    ✅ {md_rel:<30} ({format_size(size):>8}, {pages:>3} págs)")
            
    if skipped_count > 0:
        print("\n  Saltados:")
        for rel_path, status, pages, size, md_rel in results:
            if status == "skipped":
                print(f"    ⏭  {md_rel} (ya existía)")
                
    if error_count > 0:
        print("\n  Errores:")
        for rel_path, status, pages, size, md_rel in results:
            if status == "error":
                print(f"    ❌  {rel_path}")
                
    print(f"\n  📂 Salida: {output_dir}\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  🛑 Cancelado. Los .md ya completados se conservan; re-ejecuta el "
              "MISMO comando para continuar (omite lo hecho).")
        sys.exit(130)
