# PDF Quiz Generator (MVP)

Aplikasi web Python sederhana untuk membuat soal pilihan ganda dari file PDF menggunakan model Gemma 4 via Ollama.

## Fitur MVP

- Upload 1 file PDF (maks 10MB)
- Deteksi PDF teks vs PDF scan (gambar)
- Generate soal pilihan ganda (A/B/C/D) dengan jumlah 5, 10, atau 15
- Tampilkan soal di UI Gradio
- Tampilkan semua jawaban dengan satu klik
- Retry 1x otomatis jika output JSON model tidak valid

## Struktur Proyek

```text
pdf-quiz-generator/
├── app.py
├── core/
│   ├── __init__.py
│   ├── pdf_handler.py
│   ├── prompt_templates.py
│   └── quiz_generator.py
├── requirements.txt
└── README.md
```

## Prasyarat

- Python 3.11+
- Ollama terpasang
- Model Gemma 4 tersedia lokal

## Instalasi

```bash
pip install -r requirements.txt
ollama pull gemma4
ollama serve
```

## Menjalankan Aplikasi

```bash
python app.py
```

Lalu buka URL lokal dari Gradio di browser.

## Konfigurasi Opsional

Bisa menggunakan file `.env`:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4
OLLAMA_TIMEOUT_SECONDS=120
```

## Catatan

- Untuk MVP, jika PDF lebih dari 50 halaman maka hanya 10 halaman pertama yang diproses.
- Jika PDF tidak bisa dibaca atau model tidak aktif, UI akan menampilkan pesan error yang jelas.
