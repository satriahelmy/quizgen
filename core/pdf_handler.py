import base64
from pathlib import Path

import fitz


MAX_FILE_SIZE_MB = 10
MAX_PAGES_MVP = 10


class PDFProcessingError(Exception):
    pass


def validate_pdf_file(pdf_path: str) -> None:
    path = Path(pdf_path)
    if not path.exists():
        raise PDFProcessingError("File PDF tidak ditemukan.")
    if path.suffix.lower() != ".pdf":
        raise PDFProcessingError("File harus berformat PDF.")

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise PDFProcessingError("Ukuran PDF melebihi 10MB (batas MVP).")


def extract_text_from_pdf(pdf_path: str, max_pages: int = MAX_PAGES_MVP) -> str:
    doc = fitz.open(pdf_path)
    try:
        pages_to_read = min(len(doc), max_pages)
        chunks = []
        for i in range(pages_to_read):
            text = doc[i].get_text("text").strip()
            if text:
                chunks.append(text)
        return "\n\n".join(chunks).strip()
    finally:
        doc.close()


def is_scan_pdf(pdf_path: str) -> bool:
    # Heuristik sederhana: jika 3 halaman awal hampir tidak mengandung teks,
    # anggap PDF berupa hasil scan/gambar.
    doc = fitz.open(pdf_path)
    try:
        pages_to_check = min(len(doc), 3)
        text_len = 0
        for i in range(pages_to_check):
            text_len += len(doc[i].get_text("text").strip())
        return text_len < 100
    finally:
        doc.close()


def pdf_pages_to_base64_images(pdf_path: str, max_pages: int = MAX_PAGES_MVP) -> list[str]:
    doc = fitz.open(pdf_path)
    try:
        pages_to_convert = min(len(doc), max_pages)
        images_b64 = []
        for i in range(pages_to_convert):
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            image_bytes = pix.tobytes("png")
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            images_b64.append(b64)
        return images_b64
    finally:
        doc.close()


def build_content_for_model(pdf_path: str) -> dict:
    validate_pdf_file(pdf_path)

    extracted_text = extract_text_from_pdf(pdf_path)
    # Prioritaskan mode teks jika ada konten sekecil apa pun karena lebih stabil
    # untuk mayoritas model Ollama.
    if extracted_text:
        return {"mode": "text", "text": extracted_text}

    # Fallback ke mode gambar hanya jika benar-benar tidak ada teks yang bisa diambil.
    images = pdf_pages_to_base64_images(pdf_path)
    if not images:
        raise PDFProcessingError("PDF kosong atau tidak dapat diekstrak.")
    return {"mode": "image", "images": images}
