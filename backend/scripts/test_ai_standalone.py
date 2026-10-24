"""Standalone CLI runner to test AI/OCR reading, classification, extraction & local Ollama LLM.

Usage:
  1. Test all default sample files (Rule + OCR only):
     py backend/scripts/test_ai_standalone.py
  2. Test with Local Ollama LLM enabled (http://localhost:11434):
     py backend/scripts/test_ai_standalone.py --llm
  3. Test a specific PDF or Image (.png, .jpg, .jpeg) file:
     py backend/scripts/test_ai_standalone.py backend/tests/fixtures/ten_anh_cua_ban.jpg
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.ai_engine import LocalAIEngineClient  # noqa: E402
from scripts.generate_fixtures import generate_all_fixtures  # noqa: E402


def _guess_media_type(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext == ".png":
        return "image/png"
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "application/pdf"


def check_local_ollama(base_url: str, model_name: str) -> bool:
    """Check if local Ollama server is running on the machine and test a quick response."""
    print("=" * 76)
    print(f"[LLM CHECK] Checking Local Ollama at {base_url} (model={model_name})...")
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=3.0)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        print(f"[LLM CHECK] Ollama is ONLINE! Installed models: {models}")
        if not any(model_name in m for m in models):
            print(
                f"[LLM WARNING] Model '{model_name}' not found yet. "
                f"Run: ollama pull {model_name}"
            )
            return False
        return True
    except Exception as exc:
        print(
            f"[LLM CHECK] Local Ollama is NOT running or not installed ({exc}).\n"
            "  -> Install on Windows: winget install Ollama.Ollama\n"
            f"  -> Pull model:         ollama pull {model_name}"
        )
        return False


def inspect_file(
    client: LocalAIEngineClient,
    file_path: Path,
    *,
    show_full_json: bool = False,
) -> None:
    media_type = _guess_media_type(file_path)
    print("=" * 76)
    print(f"FILE: {file_path} (media_type={media_type})")
    pages = client.extract_pages(file_path=file_path, media_type=media_type)
    for p in pages:
        print(
            f"  - Page {p.page_number}: size={p.width}x{p.height}, "
            f"has_text_layer={p.has_text_layer}, rotation={p.rotation_degrees} deg, "
            f"engine={p.engine}, blocks={len(p.ocr_blocks)}"
        )

    analysis = client.analyze_document(file_path=file_path, media_type=media_type)
    print(
        f"  => AnalysisResult: engine={analysis.engine_version}, "
        f"time={analysis.processing_time_ms}ms, split_documents={len(analysis.documents)}"
    )
    for idx, doc in enumerate(analysis.documents, start=1):
        print(
            f"     [Doc #{idx}] type={doc.document_type.value!r}, "
            f"confidence={doc.classification_confidence:.2f}, "
            f"pages={doc.pages}, blocks={len(doc.ocr_blocks)}, fields={len(doc.fields)}"
        )
        for f in doc.fields:
            bbox_str = (
                f"[{f.bbox.x1:.3f}, {f.bbox.y1:.3f}, {f.bbox.x2:.3f}, {f.bbox.y2:.3f}]"
                if f.bbox
                else "None"
            )
            print(
                f"        * {f.name:22s} | raw={f.raw_value!r} -> norm={f.normalized_value!r} "
                f"(page={f.page}, bbox={bbox_str}, src={f.source})"
            )

    if show_full_json:
        print("\nFull JSON AnalysisResult:")
        print(json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False, indent=2))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    raw_args = sys.argv[1:]
    use_llm = False
    file_args: list[str] = []

    for arg in raw_args:
        if arg == "--llm":
            use_llm = True
        else:
            file_args.append(arg)

    if use_llm:
        base_url = os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
        model_name = os.environ.setdefault("OLLAMA_MODEL", "qwen2.5:1.5b")
        check_local_ollama(base_url, model_name)

    client = LocalAIEngineClient()

    if file_args:
        for arg in file_args:
            target = Path(arg)
            if not target.is_file():
                target = REPO_ROOT / arg
            inspect_file(client, target.resolve(), show_full_json=True)
        return

    # 1. Test any PDF or Image (.png, .jpg, .jpeg) files in docs/
    docs_dir = REPO_ROOT / "docs"
    if docs_dir.is_dir():
        for doc_file in sorted(docs_dir.iterdir()):
            if doc_file.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}:
                inspect_file(client, doc_file)

    # 2. Generate and test QA-01 fixture suite
    fixtures = generate_all_fixtures()
    for path in fixtures.values():
        inspect_file(client, path)


if __name__ == "__main__":
    main()
