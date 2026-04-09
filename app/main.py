from __future__ import annotations

import json
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .ai_logic import AIStudyBuddyError, explain_mistake, generate_quiz
from .database import Base, engine, get_db
from .models import Quiz
from .schemas import (
    GenerateQuizRequest,
    GenerateQuizResponse,
    MistakeExplanation,
    QuizDetailsResponse,
    QuizSummary,
    SaveQuizRequest,
    SaveQuizResponse,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Study Buddy API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DBSession = Annotated[Session, Depends(get_db)]


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateQuizResponse)
def generate(request: GenerateQuizRequest) -> GenerateQuizResponse:
    try:
        payload = generate_quiz(
            text=request.text,
            title=request.title,
            question_count=request.question_count,
        )
        return GenerateQuizResponse(**payload)
    except AIStudyBuddyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate quiz: {exc}") from exc


@app.post("/quizzes/save", response_model=SaveQuizResponse)
def save_quiz(request: SaveQuizRequest, db: DBSession) -> SaveQuizResponse:
    if len(request.questions) != len(request.user_answers):
        raise HTTPException(status_code=400, detail="Questions and answers count must match.")

    score = 0
    for question, user_answer in zip(request.questions, request.user_answers):
        if user_answer.strip() == question.correct.strip():
            score += 1

    quiz = Quiz(
        title=request.title.strip(),
        score=score,
        total_questions=len(request.questions),
        source_text=request.source_text,
        questions_json=json.dumps([question.model_dump() for question in request.questions], ensure_ascii=False),
        user_answers_json=json.dumps(request.user_answers, ensure_ascii=False),
    )

    db.add(quiz)
    db.commit()
    db.refresh(quiz)

    return SaveQuizResponse(quiz_id=quiz.id, score=score, total_questions=quiz.total_questions)


@app.get("/quizzes", response_model=list[QuizSummary])
def list_quizzes(db: DBSession) -> list[QuizSummary]:
    quizzes = db.query(Quiz).order_by(Quiz.created_at.desc()).all()
    return quizzes


@app.get("/quizzes/{quiz_id}", response_model=QuizDetailsResponse)
def get_quiz_details(quiz_id: int, db: DBSession) -> QuizDetailsResponse:
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")

    questions = json.loads(quiz.questions_json)
    user_answers = json.loads(quiz.user_answers_json)
    mistakes: list[MistakeExplanation] = []

    for question, user_answer in zip(questions, user_answers):
        if user_answer.strip() != question["correct"].strip():
            mistakes.append(
                MistakeExplanation(
                    question=question["q"],
                    selected_answer=user_answer,
                    correct_answer=question["correct"],
                    explanation="Explanation not generated yet.",
                )
            )

    return QuizDetailsResponse(quiz=QuizSummary.model_validate(quiz), mistakes=mistakes)


@app.post("/quizzes/{quiz_id}/explanations", response_model=QuizDetailsResponse)
def explain_quiz_mistakes(quiz_id: int, db: DBSession) -> QuizDetailsResponse:
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")

    questions = json.loads(quiz.questions_json)
    user_answers = json.loads(quiz.user_answers_json)
    mistakes: list[MistakeExplanation] = []

    try:
        for question, user_answer in zip(questions, user_answers):
            if user_answer.strip() != question["correct"].strip():
                explanation = explain_mistake(
                    source_text=quiz.source_text,
                    question=question["q"],
                    options=question["options"],
                    user_answer=user_answer,
                    correct_answer=question["correct"],
                )
                mistakes.append(
                    MistakeExplanation(
                        question=question["q"],
                        selected_answer=user_answer,
                        correct_answer=question["correct"],
                        explanation=explanation,
                    )
                )
    except AIStudyBuddyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to explain mistakes: {exc}") from exc

    return QuizDetailsResponse(quiz=QuizSummary.model_validate(quiz), mistakes=mistakes)
