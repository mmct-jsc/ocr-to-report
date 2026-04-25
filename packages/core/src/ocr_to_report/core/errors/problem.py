"""RFC 7807 Problem Details for HTTP APIs.

Used as the canonical error envelope across the system. The API layer
serializes :class:`ProblemDetail` directly to ``application/problem+json``
responses; the worker logs it; the CLI prints it. Domain errors expose a
``to_problem_detail()`` method.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProblemDetail(BaseModel):
    """RFC 7807 problem document.

    Reference: https://datatracker.ietf.org/doc/html/rfc7807

    The five RFC fields plus an extension dict for domain-specific data.
    Fields outside the RFC envelope go in :attr:`extensions`; serializers
    that emit ``application/problem+json`` flatten them into the top-level
    object (see :meth:`to_problem_json`).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str = Field(
        default="about:blank",
        description=(
            "URI reference identifying the problem type. 'about:blank' means"
            " no further information beyond the HTTP status text."
        ),
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Short, human-readable summary of the problem type.",
    )
    status: int = Field(
        ...,
        ge=100,
        le=599,
        description="HTTP status code (100..599).",
    )
    detail: str | None = Field(
        default=None,
        max_length=2000,
        description="Human-readable explanation specific to this occurrence.",
    )
    instance: str | None = Field(
        default=None,
        description="URI reference identifying this specific occurrence.",
    )
    extensions: dict[str, Any] = Field(
        default_factory=dict,
        description="Implementation-specific extension fields.",
    )

    def to_problem_json(self) -> dict[str, Any]:
        """Flat dict suitable for ``application/problem+json`` body.

        Extension keys are merged into the top level; collisions with RFC
        keys are silently dropped (RFC keys win).
        """
        body: dict[str, Any] = {
            "type": self.type,
            "title": self.title,
            "status": self.status,
        }
        if self.detail is not None:
            body["detail"] = self.detail
        if self.instance is not None:
            body["instance"] = self.instance
        rfc_keys = {"type", "title", "status", "detail", "instance"}
        body.update({k: v for k, v in self.extensions.items() if k not in rfc_keys})
        return body


__all__ = ["ProblemDetail"]
