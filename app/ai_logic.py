from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "openrouter/free")
DEFAULT_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")


class AIStudyBuddyError(RuntimeError):
    """Domain-specific error for AI Study Buddy operations."""


QUIZ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "options": {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 4,
                        "items": {"type": "string"},
                    },
                    "correct": {"type": "string"},
                },
                "required": ["q", "options", "correct"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "questions"],
    "additionalProperties": False,
}


def _get_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL)

    if not api_key:
        raise AIStudyBuddyError(
            "API key is missing. Add OPENROUTER_API_KEY or OPENAI_API_KEY to your .env file."
        )

    default_headers: dict[str, str] = {}
    app_url = os.getenv("OPENROUTER_APP_URL")
    app_name = os.getenv("OPENROUTER_APP_NAME")
    if app_url:
        default_headers["HTTP-Referer"] = app_url
    if app_name:
        default_headers["X-Title"] = app_name

    return OpenAI(api_key=api_key, base_url=base_url, default_headers=default_headers or None)


def _safe_title(source_text: str, fallback: str = "Study Quiz") -> str:
    first_line = next((line.strip() for line in source_text.splitlines() if line.strip()), "")
    candidate = first_line if first_line else fallback
    candidate = re.sub(r"\s+", " ", candidate).strip()
    return candidate[:70] if candidate else fallback


def _extract_json_text(response: Any) -> str:
    if getattr(response, "status", None) == "incomplete":
        reason = getattr(getattr(response, "incomplete_details", None), "reason", "unknown")
        raise AIStudyBuddyError(f"The model returned an incomplete response: {reason}.")

    if not getattr(response, "output", None):
        raise AIStudyBuddyError("The model returned an empty response.")

    first_item = response.output[0]
    if not getattr(first_item, "content", None):
        raise AIStudyBuddyError("The model did not return any content.")

    first_content = first_item.content[0]
    content_type = getattr(first_content, "type", None)

    if content_type == "refusal":
        refusal_text = getattr(first_content, "refusal", "The request was refused.")
        raise AIStudyBuddyError(refusal_text)

    text = getattr(response, "output_text", None)
    if text:
        return text

    if content_type == "output_text":
        return getattr(first_content, "text", "")

    raise AIStudyBuddyError("Unexpected model response format.")


def generate_quiz(*, text: str, title: str | None = None, question_count: int = 5) -> dict[str, Any]:
    client = _get_client()

    system_prompt = (
        "You create concise, high-quality study quizzes. "
        "Use ONLY the provided notes. Do not invent facts that are not supported by the notes. "
        "Return exactly the JSON schema requested."
    )

    requested_title = title.strip() if title and title.strip() else _safe_title(text)
    user_prompt = (
        f"Create exactly {question_count} multiple-choice questions from the study notes below.\n"
        "Requirements:\n"
        "- Each question must test understanding of the notes, not trivia.\n"
        "- Each question must have exactly 4 answer options.\n"
        "- The field 'correct' must exactly match one of the strings inside 'options'.\n"
        f"- Use this title if it fits the notes: {requested_title!r}.\n"
        "- Keep wording clear for a student.\n\n"
        "Study notes:\n"
        f"{text}"
    )

    response = client.responses.create(
        model=DEFAULT_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "study_quiz",
                "strict": True,
                "schema": QUIZ_SCHEMA,
            }
        },
    )

    payload = json.loads(_extract_json_text(response))

    quiz_title = payload.get("title") or requested_title
    questions = payload.get("questions", [])

    if len(questions) != question_count:
        raise AIStudyBuddyError(
            f"Expected {question_count} questions, but received {len(questions)}."
        )

    for index, question in enumerate(questions, start=1):
        options = [option.strip() for option in question["options"]]
        correct = question["correct"].strip()
        if correct not in options:
            raise AIStudyBuddyError(
                f"Question {index} has a correct answer that is not present in options."
            )
        question["options"] = options
        question["correct"] = correct
        question["q"] = question["q"].strip()

    return {"title": quiz_title.strip() or requested_title, "questions": questions}


def explain_mistake(*, source_text: str, question: str, options: list[str], user_answer: str, correct_answer: str) -> str:
    client = _get_client()

    prompt = (
        "You are an AI tutor helping a student understand a mistake in a quiz.\n"
        "Explain briefly and clearly in 3-5 sentences.\n"
        "1) Say why the selected answer is wrong.\n"
        "2) Say why the correct answer is right.\n"
        "3) Base the explanation only on the study notes below.\n"
        "4) If the notes are insufficient, say that explicitly.\n\n"
        f"Question: {question}\n"
        f"Options: {json.dumps(options, ensure_ascii=False)}\n"
        f"Student answer: {user_answer}\n"
        f"Correct answer: {correct_answer}\n\n"
        "Study notes:\n"
        f"{source_text}"
    )

    response = client.responses.create(
        model=DEFAULT_MODEL,
        input=[
            {
                "role": "system",
                "content": "You are a patient and practical study tutor.",
            },
            {"role": "user", "content": prompt},
        ],
    )

    explanation = response.output_text or _extract_json_text(response)
    return explanation.strip()
