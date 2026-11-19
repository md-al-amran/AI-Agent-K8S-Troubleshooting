"""Shapes of the AI diagnosis returned by POST /investigate."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["critical", "high", "medium", "low"]


class IssueDiagnosis(BaseModel):
    title: str = ""
    severity: Severity = "medium"
    affected_resources: list[str] = Field(default_factory=list)  # e.g. Deployment/default/payment-service
    root_cause: str
    explanation: str = ""
    evidence: list[str] = Field(default_factory=list)  # facts from the investigation that support the root cause
    fix: str = ""
    kubectl_commands: list[str] = Field(default_factory=list)
    prevention: str = ""
    confidence: int = Field(default=0, ge=0, le=100)
    confidence_level: Literal["high", "medium", "low"] = "low"
    confidence_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)  # e.g. a suggested command deletes resources

    # Models sometimes write "92%" or "High". Accept those instead of failing.
    @field_validator("confidence", mode="before")
    @classmethod
    def _parse_confidence(cls, value: Any) -> int:
        try:
            number = float(str(value).strip().rstrip("%"))
        except ValueError:
            return 0
        if 0 < number < 1:  # 0.92 -> 92
            number *= 100
        return int(max(0, min(100, round(number))))

    @field_validator("severity", mode="before")
    @classmethod
    def _parse_severity(cls, value: Any) -> str:
        text = str(value).strip().lower()
        return text if text in ("critical", "high", "medium", "low") else "medium"


class Diagnosis(IssueDiagnosis):
    """The most important issue at the top level, with any other issues listed below it."""

    healthy: bool = False
    summary: str = ""
    other_issues: list[IssueDiagnosis] = Field(default_factory=list)
    model: str | None = None  # None when no LLM call was needed
