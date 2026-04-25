import json
import os
import re
from typing import Any

import requests
from dotenv import load_dotenv

from core.prompt_templates import SYSTEM_PROMPT, build_user_prompt

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4")
REQUEST_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "2048"))
_RESOLVED_MODEL: str | None = None


class QuizGenerationError(Exception):
    pass


def _resolve_ollama_model() -> str:
    global _RESOLVED_MODEL
    if _RESOLVED_MODEL:
        return _RESOLVED_MODEL

    configured = OLLAMA_MODEL.strip()
    if not configured:
        configured = "gemma4"

    # Jika user sudah set model bertag penuh (mis. gemma4:e4b), pakai apa adanya.
    if ":" in configured:
        _RESOLVED_MODEL = configured
        return configured

    try:
        tags_resp = requests.get(
            f"{OLLAMA_BASE_URL}/api/tags", timeout=REQUEST_TIMEOUT
        )
        tags_resp.raise_for_status()
        models = tags_resp.json().get("models", [])
    except requests.RequestException:
        _RESOLVED_MODEL = configured
        return configured

    model_names = [str(item.get("name", "")).strip() for item in models if item]
    if configured in model_names:
        _RESOLVED_MODEL = configured
        return configured

    prefix = f"{configured}:"
    for name in model_names:
        if name.startswith(prefix):
            _RESOLVED_MODEL = name
            return name

    _RESOLVED_MODEL = configured
    return configured


def _extract_json_payload(raw_text: str) -> str:
    text = raw_text.strip()

    # 1) Ambil isi di dalam fenced code block jika ada.
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()

    # 2) Jika masih ada teks tambahan, ambil JSON array terluar pertama.
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


def _coerce_quiz_items(parsed: Any) -> Any:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        # Gemma kadang membungkus list soal dalam object.
        for key in ("quiz_questions", "questions", "items", "data", "qa_pairs", "soal"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
    return parsed


def _normalize_quiz_item_shape(item: dict) -> dict:
    # Dukung berbagai variasi key dari model.
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
            # Dukung key lower-case atau angka.
            lower = key.lower()
            numeric = str(ord(key) - 64)  # A->1, B->2, ...
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


def _call_ollama_chat(messages: list[dict]) -> str:
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": _resolve_ollama_model(),
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {
            # Prevent output being cut mid-JSON for multi-question responses.
            "num_predict": OLLAMA_NUM_PREDICT,
            "temperature": 0.2,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise QuizGenerationError("Model tidak tersedia atau gagal diakses.") from exc

    try:
        return data["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise QuizGenerationError("Respons model tidak valid.") from exc


def _build_messages_for_text(extracted_text: str, num_questions: int) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(extracted_text, num_questions)},
    ]


def _build_messages_for_images(images_b64: list[str], num_questions: int) -> list[dict]:
    content = (
        "The following inputs are PDF pages as images.\n"
        "Understand the content and generate questions according to the system prompt.\n\n"
        f"Create {num_questions} multiple-choice questions using the same JSON format."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content, "images": images_b64},
    ]


def generate_quiz(content: dict, num_questions: int) -> list[dict]:
    if content["mode"] == "text":
        messages = _build_messages_for_text(content["text"], num_questions)
    elif content["mode"] == "image":
        messages = _build_messages_for_images(content["images"], num_questions)
    else:
        raise QuizGenerationError("Mode konten tidak dikenali.")

    last_raw_output = ""
    for attempt in range(2):
        raw_output = _call_ollama_chat(messages)
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
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous output was invalid. Retry and return ONLY a valid "
                        "JSON array in the requested format."
                    ),
                }
            )

    raise QuizGenerationError("Gagal menghasilkan soal.")
