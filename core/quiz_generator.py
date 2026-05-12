import json
import os
import re
from typing import Any

from dotenv import load_dotenv
import google.generativeai as genai

from core.prompt_templates import SYSTEM_PROMPT, build_user_prompt

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "gemma-4-27b-it")

if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)


class QuizGenerationError(Exception):
    pass


# ---------------------------------------------------------------------------
# JSON extraction helpers (sama seperti versi Ollama)
# ---------------------------------------------------------------------------

def _extract_json_payload(raw_text: str) -> str:
    text = raw_text.strip()

    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()

    start = text.find("[")
    if start != -1:
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"' and not escaped:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1].strip()

    return text


def _coerce_quiz_items(parsed: Any) -> Any:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("quiz_questions", "questions", "items", "data", "qa_pairs", "soal"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
    return parsed


def _normalize_quiz_item_shape(item: dict) -> dict:
    question = (
        item.get("question")
        or item.get("soal_teks")
        or item.get("pertanyaan")
        or item.get("soal")
        or ""
    )
    options = (
        item.get("options")
        or item.get("pilihan_ganda")
        or item.get("pilihan")
        or item.get("opsi")
        or item.get("choices")
        or item.get("answers")
        or {}
    )
    answer = (
        item.get("answer")
        or item.get("kunci_jawaban")
        or item.get("jawaban")
        or item.get("kunci")
        or ""
    )
    explanation = (
        item.get("explanation")
        or item.get("penjelasan")
        or item.get("alasan")
        or ""
    )

    if isinstance(options, dict):
        normalized_options = {}
        for key in ("A", "B", "C", "D"):
            lower = key.lower()
            numeric = str(ord(key) - 64)
            value = (
                options.get(key)
                or options.get(lower)
                or options.get(numeric)
                or ""
            )
            normalized_options[key] = str(value).strip()
    elif isinstance(options, list):
        normalized_options = {}
        for idx, key in enumerate(("A", "B", "C", "D")):
            value = options[idx] if idx < len(options) else ""
            normalized_options[key] = str(value).strip()
    else:
        normalized_options = {}

    return {
        "question": str(question).strip(),
        "options": normalized_options,
        "answer": str(answer).strip(),
        "explanation": str(explanation).strip(),
    }


def _validate_quiz_items(items: Any, expected_count: int) -> list[dict]:
    if not isinstance(items, list):
        raise QuizGenerationError("Output model bukan array JSON.")

    if len(items) < expected_count:
        raise QuizGenerationError("Jumlah soal yang dihasilkan kurang dari permintaan.")

    normalized = []
    for item in items[:expected_count]:
        if not isinstance(item, dict):
            raise QuizGenerationError("Format item soal tidak valid.")

        question = item.get("question", "").strip()
        options = item.get("options", {})
        answer_raw = str(item.get("answer", "")).strip().upper()
        explanation = item.get("explanation", "").strip()
        answer = answer_raw[:1] if answer_raw else ""

        if not question or not isinstance(options, dict):
            raise QuizGenerationError("Field soal tidak lengkap.")
        for key in ("A", "B", "C", "D"):
            if key not in options or not str(options[key]).strip():
                raise QuizGenerationError("Pilihan jawaban A/B/C/D tidak lengkap.")
        if answer not in ("A", "B", "C", "D"):
            raise QuizGenerationError("Kunci jawaban tidak valid.")

        normalized.append(
            {
                "question": question,
                "options": {k: str(options[k]).strip() for k in ("A", "B", "C", "D")},
                "answer": answer,
                "explanation": explanation,
            }
        )
    return normalized


# ---------------------------------------------------------------------------
# Google AI Studio API call
# ---------------------------------------------------------------------------

def _call_gemma_api(prompt: str, image_parts: list | None = None) -> str:
    if not GOOGLE_API_KEY:
        raise QuizGenerationError(
            "GOOGLE_API_KEY tidak ditemukan. Set di file .env atau environment variable."
        )

    model = genai.GenerativeModel(
        model_name=GEMMA_MODEL,
        system_instruction=SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            temperature=0.2,
            max_output_tokens=4096,
        ),
    )

    try:
        if image_parts:
            # Multimodal: teks + gambar (halaman PDF sebagai image)
            contents = image_parts + [prompt]
        else:
            contents = [prompt]

        response = model.generate_content(contents)
        return response.text

    except Exception as exc:
        raise QuizGenerationError(f"Gagal memanggil Google AI API: {exc}") from exc


def _build_prompt_for_text(extracted_text: str, num_questions: int) -> str:
    return build_user_prompt(extracted_text, num_questions)


def _build_prompt_for_images(num_questions: int) -> tuple[str, list]:
    """Return (prompt_text, []) — image_parts sudah dihandle terpisah."""
    prompt = (
        "The following inputs are PDF pages as images.\n"
        "Understand the content and generate questions according to the system prompt.\n\n"
        f"Create {num_questions} multiple-choice questions using the same JSON format."
    )
    return prompt, []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_quiz(content: dict, num_questions: int) -> list[dict]:
    if content["mode"] == "text":
        prompt = _build_prompt_for_text(content["text"], num_questions)
        image_parts = None
    elif content["mode"] == "image":
        prompt = (
            "The following inputs are PDF pages as images. "
            "Understand the content and generate questions according to the system prompt.\n\n"
            f"Create {num_questions} multiple-choice questions using the same JSON format."
        )
        # Konversi base64 images ke format yang diterima google-generativeai
        import base64
        image_parts = []
        for b64_str in content["images"]:
            image_data = base64.b64decode(b64_str)
            image_parts.append({
                "inline_data": {
                    "mime_type": "image/png",
                    "data": b64_str,
                }
            })
        # Pakai Part langsung
        from google.generativeai.types import content_types
        image_parts = [
            genai.protos.Part(
                inline_data=genai.protos.Blob(
                    mime_type="image/png",
                    data=base64.b64decode(b64_str),
                )
            )
            for b64_str in content["images"]
        ]
    else:
        raise QuizGenerationError("Mode konten tidak dikenali.")

    last_raw_output = ""
    retry_prompt = prompt

    for attempt in range(2):
        raw_output = _call_gemma_api(retry_prompt, image_parts if content["mode"] == "image" else None)
        last_raw_output = raw_output
        cleaned_output = _extract_json_payload(raw_output)

        try:
            parsed = _coerce_quiz_items(json.loads(cleaned_output))
            if isinstance(parsed, list):
                parsed = [
                    _normalize_quiz_item_shape(x) if isinstance(x, dict) else x
                    for x in parsed
                ]
            return _validate_quiz_items(parsed, num_questions)
        except (json.JSONDecodeError, QuizGenerationError):
            if attempt == 1:
                snippet = last_raw_output.strip().replace("\n", " ")[:300]
                raise QuizGenerationError(
                    "Output JSON dari model tidak valid setelah retry. "
                    f"Contoh output model: {snippet}"
                )
            # Retry dengan instruksi tambahan
            retry_prompt = (
                "Your previous output was invalid. Retry and return ONLY a valid "
                "JSON array in the requested format. No markdown, no explanation, "
                f"just the JSON array.\n\n{prompt}"
            )

    raise QuizGenerationError("Gagal menghasilkan soal.")
