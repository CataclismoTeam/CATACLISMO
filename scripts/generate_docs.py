import os
import re
import sys
import time
from pathlib import Path

from google import genai
from google.genai import errors

# Archivo especializado donde se va a guardar la documentación
DOCS_FILE_PATH = Path("docs/TECHNICAL_DOCS.md")

# Modelo de Gemini (gemini-2.5-flash ya no está disponible para claves nuevas).
# Se puede cambiar sin tocar el código con la variable GEMINI_MODEL.
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
# Modelos de reserva, separados por comas (variable del repo GEMINI_FALLBACK_MODELS), por si el
# principal está saturado o se retira.
_raw = os.environ.get("GEMINI_FALLBACK_MODELS", "")
FALLBACKS = [m.strip() for m in _raw.split(",") if m.strip()]

# Con el repo creciendo, el prompt no puede crecer sin límite: tope por fichero y en total.
MAX_FILE_CHARS = 30_000
MAX_TOTAL_CHARS = 400_000
# Reintentos por modelo ante errores transitorios (503 saturado, 429 cuota, 500, 504)
ATTEMPTS = 5
TRANSIENT = {429, 500, 502, 503, 504}


def soft_fail(message: str) -> None:
    """La documentación es accesoria: un fallo externo avisa pero no pone main en rojo."""
    print(f"::warning title=Documentación con IA omitida::{message}")
    sys.exit(0)


def generate(client: genai.Client, prompt: str) -> str:
    """Llama a Gemini con espera exponencial y, si el modelo sigue caído, prueba el siguiente."""
    last = "sin respuesta"
    for model in [MODEL, *[m for m in FALLBACKS if m != MODEL]]:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                print(f"Calling Gemini API ({model}), intento {attempt}/{ATTEMPTS}...")
                response = client.models.generate_content(model=model, contents=prompt)
                if response.text:
                    return response.text
                last = f"{model}: respuesta vacía"
            except errors.APIError as e:
                last = f"{model}: {e.code} {e.status}"
                if e.code not in TRANSIENT:
                    break  # clave inválida, modelo inexistente...: reintentar no sirve
            if attempt < ATTEMPTS:
                time.sleep(min(60, 5 * 2 ** (attempt - 1)))  # 5, 10, 20, 40 s
    soft_fail(
        f"Gemini no respondió ({last}). Se reintentará en el próximo push a main."
    )
    return ""


def clean_markdown_output(text: str) -> str:
    """Removes outer ```markdown ... ``` wrappers if the LLM adds them."""
    text = text.strip()
    text = re.sub(r"^```(?:markdown|md)?\s*\n", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n```\s*$", "", text)
    return text.strip()


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not found.")
        sys.exit(1)

    files_to_document = sys.argv[1:]
    if not files_to_document:
        print("No modified source files provided. Skipping documentation generation.")
        sys.exit(0)

    code_context = ""
    skipped = []
    for file_path in files_to_document:
        path = Path(file_path)
        if not (path.exists() and path.is_file()):
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        if len(content) > MAX_FILE_CHARS:
            content = content[:MAX_FILE_CHARS] + "\n... [truncado por tamaño]"
        block = f"\n--- File: {file_path} ---\n```\n{content}\n```\n"
        if len(code_context) + len(block) > MAX_TOTAL_CHARS:
            skipped.append(file_path)
            continue
        code_context += block
    if skipped:
        names = ", ".join(skipped[:10])
        print(
            f"::warning::{len(skipped)} fichero(s) fuera del prompt por tamaño: {names}"
        )

    if not code_context.strip():
        print("No valid text content extracted from modified files.")
        sys.exit(0)

    # Leer documentación previa si ya existe para actualizarla sin perder contexto
    existing_docs = ""
    if DOCS_FILE_PATH.exists():
        existing_docs = DOCS_FILE_PATH.read_text(encoding="utf-8")

    prompt = f"""
You are an expert technical writer, Senior Staff Software Engineer, and hackathon mentor.
Your task is to generate or update the project's specialized technical documentation (`{DOCS_FILE_PATH.as_posix()}`) based on the latest modified source code files.

The goal of this document is twofold:
1. Help developers on the team quickly understand the evolving architecture and APIs.
2. Impress hackathon judges by clearly showcasing the technical depth, system design, data flow, and engineering rigor of the project.

### Instructions & Constraints:
- **Strict Truthfulness:** Base all technical details STRICTLY on the provided source code and existing documentation. Never hallucinate functions, endpoints, hardware pins, or libraries that are not present in the code.
- **Incremental Merge:** Preserve valid existing documentation for unchanged modules while seamlessly integrating new or updated components from the modified files. Remove or update outdated signatures.
- **Raw Markdown Output:** Return ONLY raw, valid Markdown. Do NOT wrap the entire response in ```markdown code blocks, and do NOT include conversational intros or outros.

### Required Document Structure:
# Technical Architecture & Engineering Reference

## 1. System Overview & Architecture
- High-level technical summary of how the system operates under the hood.
- Include a valid **Mermaid.js** diagram (` ```mermaid `) illustrating the architecture, module interactions, or data pipeline.

## 2. Core Modules & Components
- Breakdown of each module/file, its core responsibility, and how it interacts with the rest of the system.

## 3. API, Functions & Interfaces Reference
- Detailed documentation of key functions, classes, structs, CLI commands, or API endpoints.
- Specify parameters, types, return values, and behavior.

## 4. Configuration, Dependencies & Setup
- Required environment variables, external libraries, build flags, hardware interfaces, or execution commands detected in the codebase.

---
### Existing Documentation (`{DOCS_FILE_PATH.as_posix()}`):
{existing_docs if existing_docs else "No existing documentation yet. Generate the initial version from the provided code."}

---
### Modified / Added Source Code Files:
{code_context}
"""

    client = genai.Client(api_key=api_key)
    text = generate(client, prompt)

    cleaned_markdown = clean_markdown_output(text)

    # Asegurar que la carpeta docs/ exista y guardar el archivo
    DOCS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_FILE_PATH.write_text(cleaned_markdown + "\n", encoding="utf-8")
    print(f"Successfully updated {DOCS_FILE_PATH.as_posix()}")


if __name__ == "__main__":
    main()
