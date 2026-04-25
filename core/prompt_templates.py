SYSTEM_PROMPT = """Kamu adalah pembuat soal ujian profesional.
Tugasmu adalah membuat soal pilihan ganda berkualitas tinggi
berdasarkan materi yang diberikan.

Aturan:
- Setiap soal harus berdasarkan fakta dari teks, bukan opini
- Pilihan jawaban harus masuk akal (tidak ada jawaban yang jelas salah)
- Hanya ADA SATU jawaban yang benar
- Jawaban yang benar harus bervariasi (jangan selalu A)
- Gunakan Bahasa Indonesia yang baik dan benar
- Output HARUS dalam format JSON
"""


def build_user_prompt(extracted_text: str, num_questions: int) -> str:
    return f"""Berdasarkan materi berikut:

---
{extracted_text}
---

Buatlah {num_questions} soal pilihan ganda.

Output dalam format JSON array:
[
  {{
    "question": "...",
    "options": {{
      "A": "...",
      "B": "...",
      "C": "...",
      "D": "..."
    }},
    "answer": "A",
    "explanation": "..."
  }}
]

Hanya output JSON, tanpa teks lain.
"""
