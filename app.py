import gradio as gr

from core.pdf_handler import PDFProcessingError, build_content_for_model
from core.quiz_generator import QuizGenerationError, generate_quiz


def render_quiz(quiz_items: list[dict], show_answers: bool = False) -> str:
    lines = []
    for idx, item in enumerate(quiz_items, start=1):
        lines.append(f"### {idx}. {item['question']}")
        lines.append(f"- A. {item['options']['A']}")
        lines.append(f"- B. {item['options']['B']}")
        lines.append(f"- C. {item['options']['C']}")
        lines.append(f"- D. {item['options']['D']}")
        if show_answers:
            lines.append(f"- **Kunci Jawaban:** {item['answer']}")
            if item.get("explanation"):
                lines.append(f"- **Penjelasan:** {item['explanation']}")
        lines.append("")
    return "\n".join(lines).strip()


def generate_quiz_from_pdf(file_obj, num_questions: int, progress=gr.Progress()):
    if file_obj is None:
        return "Silakan upload file PDF terlebih dahulu.", "Belum ada hasil.", None

    try:
        progress(0.1, desc="Validasi file PDF...")
        status = "Sedang memproses PDF..."

        progress(0.35, desc="Ekstraksi konten PDF...")
        content = build_content_for_model(file_obj.name)

        progress(0.65, desc="Generate soal dengan Gemma 4...")
        quiz_items = generate_quiz(content, int(num_questions))

        progress(0.95, desc="Menyiapkan tampilan hasil...")
        rendered = render_quiz(quiz_items, show_answers=False)
        progress(1.0, desc="Selesai.")
        return "Selesai. Soal berhasil digenerate.", rendered, quiz_items
    except (PDFProcessingError, QuizGenerationError) as exc:
        return f"Gagal: {exc}", f"Error: {exc}", None
    except Exception as exc:  # fallback agar UI tetap ramah pengguna
        return f"Gagal: {exc}", f"Terjadi error tidak terduga: {exc}", None


def reveal_answers(quiz_state):
    if not quiz_state:
        return "Belum ada soal yang bisa ditampilkan jawabannya."
    return render_quiz(quiz_state, show_answers=True)


with gr.Blocks(title="PDF Quiz Generator") as demo:
    gr.Markdown("# PDF Quiz Generator - Powered by Gemma 4")
    gr.Markdown("Upload PDF, pilih jumlah soal, lalu generate quiz otomatis.")

    with gr.Row():
        pdf_input = gr.File(label="Upload PDF", file_types=[".pdf"], type="filepath")
        num_questions = gr.Radio(
            choices=[5, 10, 15],
            value=10,
            label="Jumlah soal",
        )

    generate_btn = gr.Button("Generate Soal", variant="primary")
    reveal_btn = gr.Button("Tampilkan Semua Jawaban")

    status_md = gr.Markdown("Status: siap.")
    result_md = gr.Markdown(label="Hasil")
    quiz_state = gr.State(value=None)

    generate_btn.click(
        fn=generate_quiz_from_pdf,
        inputs=[pdf_input, num_questions],
        outputs=[status_md, result_md, quiz_state],
    )
    reveal_btn.click(
        fn=reveal_answers,
        inputs=[quiz_state],
        outputs=[result_md],
    )


if __name__ == "__main__":
    demo.launch()
