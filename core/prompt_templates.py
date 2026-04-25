SYSTEM_PROMPT = """You are a professional exam question writer.
Your task is to create high-quality multiple-choice questions
based on the provided material.

Rules:
- Every question must be based on facts from the material, not opinions
- Answer options must be plausible (no obviously wrong distractors)
- There must be exactly ONE correct answer
- Correct answers should be varied (not always A)
- Use clear and natural English
- Output MUST be valid JSON
"""


def build_user_prompt(extracted_text: str, num_questions: int) -> str:
    return f"""Based on the following material:

---
{extracted_text}
---

Create {num_questions} multiple-choice questions.

Return output in this JSON array format:
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

Output JSON only, without any extra text.
"""
