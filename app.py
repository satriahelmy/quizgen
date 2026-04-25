import os
import json
import uuid
from io import BytesIO

from flask import Flask, jsonify, render_template, request, send_file, url_for
import fitz
from sqlalchemy import inspect, text
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.pdf_handler import (
    PDFProcessingError,
    build_content_for_model,
    validate_pdf_file,
)
from core.quiz_generator import QuizGenerationError, generate_quiz
from database import db, PDF, QuizSession, Question, QuizAttempt

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///quizgen.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = "uploads"

db.init_app(app)


def _default_topic_name(filename: str) -> str:
    stem = os.path.splitext(filename)[0].strip()
    return stem[:255] if stem else "Untitled Topic"


def _ensure_database_upgrades() -> None:
    inspector = inspect(db.engine)
    pdf_columns = {col["name"] for col in inspector.get_columns("pdf")}
    if "topic_name" not in pdf_columns:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE pdf ADD COLUMN topic_name VARCHAR(255)"))

    # Backfill existing rows for better readability.
    with db.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE pdf SET topic_name = original_filename "
                "WHERE topic_name IS NULL OR topic_name = ''"
            )
        )


with app.app_context():
    db.create_all()
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    _ensure_database_upgrades()


def _build_review_items_for_attempt(session: QuizSession, attempt: QuizAttempt) -> list[dict]:
    answer_map = json.loads(attempt.answers or "{}")
    questions = (
        Question.query.filter_by(session_id=session.id).order_by(Question.order.asc()).all()
    )

    review_items = []
    for q in questions:
        user_answer = str(answer_map.get(str(q.id), "")).upper().strip()[:1]
        review_items.append(
            {
                "order": q.order,
                "question": q.question_text,
                "user_answer": user_answer or "-",
                "correct_answer": q.correct_answer,
                "is_correct": user_answer == q.correct_answer,
                "explanation": q.explanation or "",
                "options": {
                    "A": q.option_a,
                    "B": q.option_b,
                    "C": q.option_c,
                    "D": q.option_d,
                },
            }
        )
    return review_items


@app.route("/", methods=["GET", "POST"])
def index():
    pdfs = PDF.query.order_by(PDF.uploaded_at.desc()).all()
    return render_template("library.html", pdfs=pdfs)


@app.route("/library", methods=["GET"])
def library():
    pdfs = PDF.query.order_by(PDF.uploaded_at.desc()).all()
    return render_template("library.html", pdfs=pdfs)


@app.route("/api/pdf/upload", methods=["POST"])
def api_pdf_upload():
    file_obj = request.files.get("pdf_file")
    if not file_obj or not file_obj.filename:
        return jsonify({"error": "Please upload a PDF file first."}), 400

    original_filename = file_obj.filename
    topic_name = (request.form.get("topic_name") or "").strip()
    if not topic_name:
        topic_name = _default_topic_name(original_filename)
    topic_name = topic_name[:255]
    stored_filename = f"{uuid.uuid4()}_{original_filename}"
    stored_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_filename)

    try:
        file_obj.save(stored_path)
        validate_pdf_file(stored_path)
        # Use existing function to ensure PDF is processable.
        _ = build_content_for_model(stored_path)
        with fitz.open(stored_path) as doc:
            page_count = len(doc)
        file_size = os.path.getsize(stored_path)
    except Exception as exc:
        if os.path.exists(stored_path):
            os.remove(stored_path)
        return jsonify({"error": f"Failed to process PDF: {exc}"}), 400

    pdf = PDF(
        topic_name=topic_name,
        original_filename=original_filename,
        stored_filename=stored_filename,
        page_count=page_count,
        file_size=file_size,
    )
    db.session.add(pdf)
    db.session.commit()
    return (
        jsonify(
            {
                "id": pdf.id,
                "topic_name": pdf.topic_name,
                "original_filename": pdf.original_filename,
                "page_count": pdf.page_count,
                "file_size": pdf.file_size,
            }
        ),
        201,
    )


@app.route("/api/pdf/<int:pdf_id>", methods=["DELETE"])
def api_pdf_delete(pdf_id: int):
    pdf = PDF.query.get_or_404(pdf_id)
    stored_path = os.path.join(app.config["UPLOAD_FOLDER"], pdf.stored_filename)
    if os.path.exists(stored_path):
        os.remove(stored_path)
    db.session.delete(pdf)
    db.session.commit()
    return jsonify({"success": True})


@app.route("/api/pdf/<int:pdf_id>/topic", methods=["PATCH"])
def api_pdf_update_topic(pdf_id: int):
    pdf = PDF.query.get_or_404(pdf_id)
    payload = request.get_json(silent=True) or request.form
    topic_name = str(payload.get("topic_name", "")).strip()
    if not topic_name:
        return jsonify({"error": "Topic name is required."}), 400

    pdf.topic_name = topic_name[:255]
    db.session.commit()
    return jsonify({"success": True, "id": pdf.id, "topic_name": pdf.topic_name})


@app.route("/api/quiz/generate", methods=["POST"])
def api_quiz_generate():
    payload = request.get_json(silent=True) or request.form
    pdf_id_raw = payload.get("pdf_id")
    num_questions_raw = payload.get("num_questions", 10)
    generation_mode = str(payload.get("mode", "reuse")).strip().lower()

    try:
        pdf_id = int(pdf_id_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid pdf_id."}), 400

    try:
        num_questions = int(num_questions_raw)
    except (TypeError, ValueError):
        num_questions = 10
    if num_questions not in (5, 10, 15):
        num_questions = 10

    pdf = PDF.query.get_or_404(pdf_id)
    stored_path = os.path.join(app.config["UPLOAD_FOLDER"], pdf.stored_filename)
    if not os.path.exists(stored_path):
        return jsonify({"error": "PDF file was not found on the server."}), 404

    if generation_mode == "reuse":
        latest_session = (
            QuizSession.query.filter_by(pdf_id=pdf.id, num_questions=num_questions)
            .order_by(QuizSession.created_at.desc())
            .first()
        )
        if latest_session:
            question_count = Question.query.filter_by(session_id=latest_session.id).count()
            if question_count >= num_questions:
                return jsonify(
                    {
                        "session_id": latest_session.id,
                        "reused": True,
                        "redirect_url": url_for("quiz_page", session_id=latest_session.id),
                    }
                )

    try:
        content = build_content_for_model(stored_path)
        quiz_items = generate_quiz(content, num_questions)
    except (PDFProcessingError, QuizGenerationError) as exc:
        return jsonify({"error": str(exc)}), 400

    session = QuizSession(pdf_id=pdf.id, num_questions=num_questions)
    db.session.add(session)
    db.session.flush()

    for idx, item in enumerate(quiz_items, start=1):
        question = Question(
            session_id=session.id,
            order=idx,
            question_text=item["question"],
            option_a=item["options"]["A"],
            option_b=item["options"]["B"],
            option_c=item["options"]["C"],
            option_d=item["options"]["D"],
            correct_answer=item["answer"],
            explanation=item.get("explanation"),
        )
        db.session.add(question)
    db.session.commit()

    return jsonify(
        {
            "session_id": session.id,
            "reused": False,
            "redirect_url": url_for("quiz_page", session_id=session.id),
        }
    )


@app.route("/quiz/<session_id>", methods=["GET"])
def quiz_page(session_id: str):
    session = QuizSession.query.get_or_404(session_id)
    baseline_attempt_id = request.args.get("baseline_attempt_id", type=int)
    return render_template(
        "quiz.html",
        session=session,
        baseline_attempt_id=baseline_attempt_id,
    )


@app.route("/api/quiz/<session_id>/questions", methods=["GET"])
def api_quiz_questions(session_id: str):
    session = QuizSession.query.get_or_404(session_id)
    questions = (
        Question.query.filter_by(session_id=session.id).order_by(Question.order.asc()).all()
    )
    return jsonify(
        {
            "session_id": session.id,
            "num_questions": session.num_questions,
            "questions": [
                {
                    "id": q.id,
                    "order": q.order,
                    "question": q.question_text,
                    "options": {
                        "A": q.option_a,
                        "B": q.option_b,
                        "C": q.option_c,
                        "D": q.option_d,
                    },
                    "correct_answer": q.correct_answer,
                    "explanation": q.explanation or "",
                }
                for q in questions
            ],
        }
    )


@app.route("/api/quiz/<session_id>/submit", methods=["POST"])
def api_quiz_submit(session_id: str):
    session = QuizSession.query.get_or_404(session_id)
    payload = request.get_json(silent=True) or {}
    answers = payload.get("answers", {})
    baseline_attempt_id = payload.get("baseline_attempt_id")
    if not isinstance(answers, dict):
        return jsonify({"error": "answers must be a JSON object."}), 400

    questions = (
        Question.query.filter_by(session_id=session.id).order_by(Question.order.asc()).all()
    )
    total = len(questions)
    score = 0
    review_items = []
    normalized_answers = {}

    for q in questions:
        key = str(q.id)
        user_answer = str(answers.get(key, "")).upper().strip()[:1]
        is_correct = user_answer == q.correct_answer
        if is_correct:
            score += 1
        normalized_answers[key] = user_answer
        review_items.append(
            {
                "question_id": q.id,
                "question": q.question_text,
                "user_answer": user_answer,
                "correct_answer": q.correct_answer,
                "is_correct": is_correct,
                "explanation": q.explanation or "",
            }
        )

    attempt = QuizAttempt(
        session_id=session.id,
        score=score,
        total=total,
        answers=json.dumps(normalized_answers),
    )
    db.session.add(attempt)
    db.session.commit()

    compare_to_attempt = None
    if baseline_attempt_id is not None:
        try:
            baseline_attempt_id = int(baseline_attempt_id)
            compare_to_attempt = QuizAttempt.query.get(baseline_attempt_id)
        except (TypeError, ValueError):
            compare_to_attempt = None

    result_url = url_for("result_page", session_id=session.id, attempt_id=attempt.id)
    if compare_to_attempt:
        result_url = url_for(
            "result_page",
            session_id=session.id,
            attempt_id=attempt.id,
            compare_to=compare_to_attempt.id,
        )

    return jsonify(
        {
            "attempt_id": attempt.id,
            "score": score,
            "total": total,
            "review": review_items,
            "result_url": result_url,
        }
    )


@app.route("/result/<session_id>/<int:attempt_id>", methods=["GET"])
def result_page(session_id: str, attempt_id: int):
    session = QuizSession.query.get_or_404(session_id)
    attempt = QuizAttempt.query.filter_by(id=attempt_id, session_id=session.id).first_or_404()
    review_items = _build_review_items_for_attempt(session, attempt)
    percentage = int((attempt.score / attempt.total) * 100) if attempt.total else 0
    wrong_count = sum(1 for item in review_items if not item["is_correct"])

    compare_to = request.args.get("compare_to", type=int)
    improvement = None
    if compare_to:
        baseline_attempt = QuizAttempt.query.get(compare_to)
        if baseline_attempt and baseline_attempt.total:
            baseline_pct = (baseline_attempt.score / baseline_attempt.total) * 100
            delta = round(percentage - baseline_pct, 1)
            improvement = {
                "baseline_percentage": round(baseline_pct, 1),
                "delta": delta,
                "direction": "up" if delta > 0 else ("down" if delta < 0 else "same"),
            }

    return render_template(
        "result.html",
        session=session,
        attempt=attempt,
        review_items=review_items,
        percentage=percentage,
        wrong_count=wrong_count,
        improvement=improvement,
    )


@app.route("/api/result/<session_id>/<int:attempt_id>/export-pdf", methods=["GET"])
def export_result_pdf(session_id: str, attempt_id: int):
    session = QuizSession.query.get_or_404(session_id)
    attempt = QuizAttempt.query.filter_by(id=attempt_id, session_id=session.id).first_or_404()
    review_items = _build_review_items_for_attempt(session, attempt)
    percentage = int((attempt.score / attempt.total) * 100) if attempt.total else 0
    topic_name = session.pdf.topic_name or session.pdf.original_filename

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()
    body_style = styles["Normal"].clone("BodySmall")
    body_style.fontSize = 9
    body_style.leading = 12
    body = []

    body.append(Paragraph("QUIZGEN - Quiz Result Report", styles["Title"]))
    body.append(Spacer(1, 8))
    body.append(Paragraph(f"<b>Topic:</b> {topic_name}", styles["Normal"]))
    body.append(Paragraph(f"<b>Session ID:</b> {session.id}", styles["Normal"]))
    body.append(
        Paragraph(
            f"<b>Score:</b> {attempt.score}/{attempt.total} ({percentage}%)",
            styles["Normal"],
        )
    )
    body.append(
        Paragraph(
            f"<b>Completed:</b> {attempt.completed_at.strftime('%Y-%m-%d %H:%M:%S')}",
            styles["Normal"],
        )
    )
    body.append(Spacer(1, 12))

    for item in review_items:
        status = "Correct" if item["is_correct"] else "Incorrect"
        status_color = "#166534" if item["is_correct"] else "#991B1B"
        body.append(
            Paragraph(
                f"<b>Q{item['order']}.</b> {item['question']}",
                styles["Heading4"],
            )
        )

        user_answer_key = item["user_answer"] if item["user_answer"] in ("A", "B", "C", "D") else "-"
        correct_answer_key = item["correct_answer"] if item["correct_answer"] in ("A", "B", "C", "D") else "-"
        user_answer_text = (
            item["options"].get(user_answer_key, "-") if user_answer_key != "-" else "-"
        )
        correct_answer_text = (
            item["options"].get(correct_answer_key, "-") if correct_answer_key != "-" else "-"
        )

        table_data = [
            [Paragraph("<b>Status</b>", body_style), Paragraph(f"<font color='{status_color}'><b>{status}</b></font>", body_style)],
            [Paragraph("<b>Your Answer</b>", body_style), Paragraph(f"{item['user_answer']} - {user_answer_text}", body_style)],
            [Paragraph("<b>Correct Answer</b>", body_style), Paragraph(f"{item['correct_answer']} - {correct_answer_text}", body_style)],
            [Paragraph("<b>Options</b>", body_style), Paragraph(
                f"A. {item['options']['A']}<br/>"
                f"B. {item['options']['B']}<br/>"
                f"C. {item['options']['C']}<br/>"
                f"D. {item['options']['D']}",
                body_style,
            )],
        ]
        if item["explanation"]:
            table_data.append(
                [
                    Paragraph("<b>Explanation</b>", body_style),
                    Paragraph(item["explanation"], body_style),
                ]
            )

        table = Table(table_data, colWidths=[110, 385], repeatRows=0)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        body.append(table)
        body.append(Spacer(1, 10))

    doc.build(body)
    buffer.seek(0)
    filename = f"quiz-result-{session.id[:8]}-attempt-{attempt.id}.pdf"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@app.route("/api/quiz/<session_id>/<int:attempt_id>/retry-wrong", methods=["POST"])
def api_retry_wrong_questions(session_id: str, attempt_id: int):
    session = QuizSession.query.get_or_404(session_id)
    attempt = QuizAttempt.query.filter_by(id=attempt_id, session_id=session.id).first_or_404()
    answer_map = json.loads(attempt.answers or "{}")
    questions = (
        Question.query.filter_by(session_id=session.id).order_by(Question.order.asc()).all()
    )

    wrong_questions = []
    for q in questions:
        user_answer = str(answer_map.get(str(q.id), "")).upper().strip()[:1]
        if user_answer != q.correct_answer:
            wrong_questions.append(q)

    if not wrong_questions:
        return jsonify({"error": "No incorrect answers found for remediation."}), 400

    remedial_session = QuizSession(pdf_id=session.pdf_id, num_questions=len(wrong_questions))
    db.session.add(remedial_session)
    db.session.flush()

    for idx, q in enumerate(wrong_questions, start=1):
        cloned = Question(
            session_id=remedial_session.id,
            order=idx,
            question_text=q.question_text,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            correct_answer=q.correct_answer,
            explanation=q.explanation,
        )
        db.session.add(cloned)
    db.session.commit()

    return jsonify(
        {
            "session_id": remedial_session.id,
            "redirect_url": url_for(
                "quiz_page",
                session_id=remedial_session.id,
                baseline_attempt_id=attempt.id,
            ),
            "question_count": len(wrong_questions),
        }
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=7860, debug=True)
