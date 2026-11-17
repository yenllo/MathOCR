import requests
import json

def clean_text_with_ollama(raw_text, model_name="phi3"):
    """
    Pasada OPCIONAL de SOLO FORMATO con un LLM local (Ollama).

    No corrige ortografía ni semántica: únicamente ajusta espaciado y formato.
    Está pensada para no poder cambiar el contenido matemático (signos, números,
    LaTeX). Es opt-in vía --clean-llm; la limpieza por defecto es determinista.
    """
    url = "http://localhost:11434/api/generate"

    system_prompt = (
        "Eres un normalizador de FORMATO de texto. Tu ÚNICA tarea es arreglar el espaciado "
        "(espacios dobles, espacios antes de comas/puntos, espacios al final de línea, líneas "
        "en blanco sobrantes). "
        "PROHIBIDO ABSOLUTO: no cambies, agregues ni borres NINGUNA palabra, letra, número, signo "
        "(+, -, =, <, >), símbolo ni puntuación. No corrijas ortografía. No traduzcas. No resumas. "
        "No 'mejores' nada. El contenido matemático debe quedar idéntico carácter por carácter. "
        "REGLA DE ORO: nunca toques lo que esté entre signos de dólar ($ o $$); el LaTeX queda intacto. "
        "Devuelve EXCLUSIVAMENTE el mismo texto con el espaciado normalizado, sin saludos, sin "
        "explicaciones y sin formato extra."
    )
    
    payload = {
        "model": model_name,
        "prompt": raw_text,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "top_p": 0.9
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=300)
        response.raise_for_status()
        result = response.json()
        return result.get("response", raw_text).strip()
    except Exception as e:
        print(f"\n  [⚠️ Error conectando a Ollama ({model_name}): {e}. Usando texto original.]")
        return raw_text
