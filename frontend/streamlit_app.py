from __future__ import annotations

import os
from io import BytesIO
from typing import Any

import requests
import streamlit as st
from docx import Document
from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
TIMEOUT = 120
SUPPORTED_EXTENSIONS = ["txt", "md", "pdf", "docx"]

st.set_page_config(page_title="AI Study Buddy", page_icon="📘", layout="wide")


def api_get(path: str) -> Any:
    response = requests.get(f"{BACKEND_URL}{path}", timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def api_post(path: str, payload: dict[str, Any]) -> Any:
    response = requests.post(f"{BACKEND_URL}{path}", json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def _decode_text_file(raw_bytes: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode the text file.")


@st.cache_data(show_spinner=False)
def extract_text_from_upload(file_name: str, file_bytes: bytes) -> str:
    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

    if extension in {"txt", "md"}:
        return _decode_text_file(file_bytes).strip()

    if extension == "pdf":
        reader = PdfReader(BytesIO(file_bytes))
        pages: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n\n".join(page.strip() for page in pages if page.strip()).strip()

    if extension == "docx":
        document = Document(BytesIO(file_bytes))
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        return "\n".join(paragraphs).strip()

    raise ValueError("Unsupported file type. Upload TXT, MD, PDF, or DOCX.")


if "quiz_title" not in st.session_state:
    st.session_state.quiz_title = ""
if "source_text" not in st.session_state:
    st.session_state.source_text = ""
if "generated_quiz" not in st.session_state:
    st.session_state.generated_quiz = None
if "submitted_result" not in st.session_state:
    st.session_state.submitted_result = None
if "explanations_cache" not in st.session_state:
    st.session_state.explanations_cache = {}


st.title("📘 AI Study Buddy")
st.caption("Upload a file or paste notes, generate a quiz, save results, and get AI explanations for mistakes.")

page = st.sidebar.radio("Navigation", ["Generate Quiz", "History"])

if page == "Generate Quiz":
    left, right = st.columns([1.1, 1])

    with left:
        st.subheader("1. Create a quiz")
        source_mode = st.radio(
            "Choose input type",
            options=["Upload file", "Paste notes"],
            horizontal=True,
        )

        with st.form("generate_form"):
            title = st.text_input(
                "Topic title",
                value=st.session_state.quiz_title,
                placeholder="Example: Neural Networks Basics",
            )

            uploaded_file = None
            source_text = ""

            if source_mode == "Upload file":
                uploaded_file = st.file_uploader(
                    "Upload your study file",
                    type=SUPPORTED_EXTENSIONS,
                    help="Supported formats: TXT, MD, PDF, DOCX",
                )
                st.caption("Best for lecture notes, summaries, exported readings, or homework drafts.")
            else:
                source_text = st.text_area(
                    "Paste your notes",
                    value=st.session_state.source_text,
                    height=300,
                    placeholder="Paste your lecture notes, summary, or study materials here...",
                )

            question_count = st.slider("Number of questions", min_value=3, max_value=10, value=5)
            generate_clicked = st.form_submit_button("Generate quiz")

        if generate_clicked:
            st.session_state.submitted_result = None
            st.session_state.generated_quiz = None
            try:
                if source_mode == "Upload file":
                    if uploaded_file is None:
                        raise ValueError("Upload a file first.")
                    file_bytes = uploaded_file.getvalue()
                    source_text = extract_text_from_upload(uploaded_file.name, file_bytes)
                    if len(source_text) < 50:
                        raise ValueError(
                            "The uploaded file does not contain enough readable text. Try another file."
                        )
                    if not title.strip():
                        title = uploaded_file.name.rsplit(".", 1)[0]
                else:
                    source_text = source_text.strip()
                    if len(source_text) < 50:
                        raise ValueError("Paste at least a short set of notes before generating a quiz.")

                st.session_state.quiz_title = title
                st.session_state.source_text = source_text

                with st.spinner("Generating quiz..."):
                    quiz = api_post(
                        "/generate",
                        {
                            "title": title or None,
                            "text": source_text,
                            "question_count": question_count,
                        },
                    )
                st.session_state.generated_quiz = quiz
                st.success("Quiz generated.")
            except requests.HTTPError as exc:
                detail = exc.response.json().get("detail", exc.response.text)
                st.error(detail)
            except Exception as exc:
                st.error(f"Failed to generate quiz: {exc}")

        if source_mode == "Upload file" and st.session_state.source_text:
            with st.expander("Preview extracted text"):
                preview = st.session_state.source_text[:3000]
                st.text(preview if preview else "No text extracted yet.")
                if len(st.session_state.source_text) > 3000:
                    st.caption("Preview truncated to 3000 characters.")

    with right:
        st.subheader("2. Take the quiz")
        quiz = st.session_state.generated_quiz
        if not quiz:
            st.info("Generate a quiz first.")
        else:
            st.markdown(f"**Topic:** {quiz['title']}")
            with st.form("quiz_form"):
                answers: list[str] = []
                for idx, question in enumerate(quiz["questions"], start=1):
                    st.markdown(f"**{idx}. {question['q']}**")
                    answer = st.radio(
                        label=f"Choose an answer for question {idx}",
                        options=question["options"],
                        key=f"question_{idx}",
                        label_visibility="collapsed",
                    )
                    answers.append(answer)
                submit_clicked = st.form_submit_button("Finish quiz")

            if submit_clicked:
                try:
                    result = api_post(
                        "/quizzes/save",
                        {
                            "title": quiz["title"],
                            "source_text": st.session_state.source_text,
                            "questions": quiz["questions"],
                            "user_answers": answers,
                        },
                    )
                    st.session_state.submitted_result = result
                    st.success(
                        f"Saved. Your score: {result['score']}/{result['total_questions']}"
                    )
                except requests.HTTPError as exc:
                    detail = exc.response.json().get("detail", exc.response.text)
                    st.error(detail)
                except Exception as exc:
                    st.error(f"Failed to save quiz result: {exc}")

        if st.session_state.submitted_result:
            st.metric(
                "Latest result",
                f"{st.session_state.submitted_result['score']}/{st.session_state.submitted_result['total_questions']}",
            )

else:
    st.subheader("Quiz history")
    st.write("See past results and generate explanations for mistakes.")

    try:
        quizzes = api_get("/quizzes")
    except Exception as exc:
        quizzes = []
        st.error(f"Failed to load history: {exc}")

    if not quizzes:
        st.info("No quizzes saved yet.")
    else:
        for quiz in quizzes:
            with st.container(border=True):
                st.markdown(f"### {quiz['title']}")
                st.write(f"**Score:** {quiz['score']}/{quiz['total_questions']}")
                st.write(f"**Date:** {quiz['created_at']}")

                cols = st.columns([1, 3])
                with cols[0]:
                    if st.button("See mistakes", key=f"mistakes_{quiz['id']}"):
                        try:
                            with st.spinner("Generating explanations..."):
                                st.session_state.explanations_cache[quiz["id"]] = api_post(
                                    f"/quizzes/{quiz['id']}/explanations",
                                    {},
                                )
                        except requests.HTTPError as exc:
                            detail = exc.response.json().get("detail", exc.response.text)
                            st.error(detail)
                        except Exception as exc:
                            st.error(f"Failed to generate explanations: {exc}")

                cached = st.session_state.explanations_cache.get(quiz["id"])
                if cached is not None:
                    if not cached["mistakes"]:
                        st.success("Perfect score — no mistakes to explain.")
                    else:
                        for idx, mistake in enumerate(cached["mistakes"], start=1):
                            with st.expander(f"Mistake {idx}: {mistake['question']}"):
                                st.write(f"**Your answer:** {mistake['selected_answer']}")
                                st.write(f"**Correct answer:** {mistake['correct_answer']}")
                                st.write(mistake['explanation'])
