# QUIZGEN (Flask + Ollama)

QUIZGEN is a Flask web app that generates multiple-choice quizzes from PDFs using Gemma 4 via Ollama.

## Features

- PDF question bank (upload once, reuse many times)
- Generate quiz sessions with 5, 10, or 15 questions
- Mode selection when generating:
  - Reuse last generated set
  - Generate a new set
- Interactive quiz mode:
  - One question per screen
  - Instant correctness feedback
  - Explanation after answering
- Results page:
  - Score and percentage
  - Per-question review
- Remedial mode:
  - Start a new session from previously incorrect answers only
  - Improvement badge vs previous attempt
- SQLite persistence with SQLAlchemy:
  - PDFs
  - Quiz sessions
  - Questions
  - Attempts

## Tech Stack

- Python 3.11+
- Flask
- Flask-SQLAlchemy
- PyMuPDF (`fitz`)
- Ollama (Gemma 4)
- Requests

## Project Structure

```text
quizgen/
├── app.py
├── database.py
├── core/
│   ├── __init__.py
│   ├── pdf_handler.py
│   ├── prompt_templates.py
│   └── quiz_generator.py
├── templates/
│   ├── base.html
│   ├── library.html
│   ├── quiz.html
│   └── result.html
├── uploads/                  # created automatically at runtime
├── requirements.txt
└── README.md
```

## Installation

```bash
pip install -r requirements.txt
ollama pull gemma4
ollama serve
```

## Run

```bash
python app.py
```

Open:
- http://127.0.0.1:7860

## Main Routes

- `GET /` - PDF question bank (home)
- `GET /library` - PDF question bank
- `POST /api/pdf/upload` - Upload and save PDF
- `DELETE /api/pdf/<id>` - Delete PDF
- `POST /api/quiz/generate` - Generate or reuse quiz session
- `GET /quiz/<session_id>` - Interactive quiz page
- `GET /api/quiz/<session_id>/questions` - Quiz questions JSON
- `POST /api/quiz/<session_id>/submit` - Submit answers
- `GET /result/<session_id>/<attempt_id>` - Quiz results page
- `POST /api/quiz/<session_id>/<attempt_id>/retry-wrong` - Create remedial session

## Optional Environment Variables

Create a `.env` file if needed:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4
OLLAMA_TIMEOUT_SECONDS=120
```

## Notes

- The app validates uploaded files as PDF and stores metadata in SQLite (`quizgen.db`).
- If model output is malformed, quiz generation includes parsing/normalization safeguards.
- If Ollama is unavailable, the API returns a clear error message.
