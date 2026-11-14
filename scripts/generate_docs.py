import os
import re
import sys
from pathlib import Path
from google import genai

# Archivo especializado donde se va a guardar la documentación
DOCS_FILE_PATH = Path("docs/TECHNICAL_DOCS.md")

# Modelo de Gemini (gemini-2.5-flash ya no está disponible para claves nuevas).
# Se puede cambiar sin tocar el código con la variable GEMINI_MODEL.
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"

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
    for file_path in files_to_document:
        path = Path(file_path)
        if path.exists() and path.is_file():
            content = path.read_text(encoding="utf-8", errors="ignore")
            code_context += f"\n--- File: {file_path} ---\n```\n{content}\n```\n"

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

    print(f"Calling Gemini API ({MODEL}) to generate technical documentation...")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )

    if not response.text:
        print("Error: Received empty response from Gemini.")
        sys.exit(1)

    cleaned_markdown = clean_markdown_output(response.text)

    # Asegurar que la carpeta docs/ exista y guardar el archivo
    DOCS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_FILE_PATH.write_text(cleaned_markdown + "\n", encoding="utf-8")
    print(f"Successfully updated {DOCS_FILE_PATH.as_posix()}")

if __name__ == "__main__":
    main()
