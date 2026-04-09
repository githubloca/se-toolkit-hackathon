from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel, Field, field_validator


class GenerateQuizRequest(BaseModel):
    text: str = Field(min_length=50, description="Study notes used to generate the quiz")
    title: str | None = Field(default=None, description="Optional quiz title")
    question_count: int = Field(default=5, ge=1, le=10)


class QuizQuestion(BaseModel):
    q: str = Field(min_length=5)
    options: List[str] = Field(min_length=3, max_length=5)
    correct: str = Field(min_length=1)

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: List[str]) -> List[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if len(cleaned) < 3:
            raise ValueError("Each question must contain at least 3 options.")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("Answer options must be unique.")
        return cleaned

    @field_validator("correct")
    @classmethod
    def validate_correct(cls, value: str) -> str:
        return value.strip()


class GenerateQuizResponse(BaseModel):
    title: str
    questions: List[QuizQuestion]


class SaveQuizRequest(BaseModel):
    title: str = Field(min_length=1)
    source_text: str = Field(min_length=50)
    questions: List[QuizQuestion] = Field(min_length=1)
    user_answers: List[str] = Field(min_length=1)

    @field_validator("user_answers")
    @classmethod
    def validate_answers(cls, value: List[str]) -> List[str]:
        return [answer.strip() for answer in value]


class SaveQuizResponse(BaseModel):
    quiz_id: int
    score: int
    total_questions: int


class QuizSummary(BaseModel):
    id: int
    title: str
    score: int
    total_questions: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MistakeExplanation(BaseModel):
    question: str
    selected_answer: str
    correct_answer: str
    explanation: str


class QuizDetailsResponse(BaseModel):
    quiz: QuizSummary
    mistakes: List[MistakeExplanation]
