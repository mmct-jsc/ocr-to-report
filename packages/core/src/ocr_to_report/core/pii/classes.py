"""PII classification taxonomy.

Drives auto-redaction in logs, audit metadata, and (optionally) webhook
payloads. Each classification has explicit handling rules documented inline.
"""

from __future__ import annotations

from enum import StrEnum


class PIIClass(StrEnum):
    """Classification of a single field's privacy/confidentiality level.

    Order matters: items later in the enum are *more* sensitive. Use
    :py:meth:`is_sensitive` to test if redaction is required for log output.
    """

    PUBLIC = "public"
    """Non-sensitive data. Safe to log, audit, and emit in webhooks."""

    INTERNAL = "internal"
    """Operationally useful, not personally identifying. Safe to log; audit
    metadata may include verbatim. Examples: provider id, schema version."""

    PII_QUASI = "pii_quasi"
    """Quasi-identifiers — alone they don't identify, but combined with
    others (e.g., school + city + birth year) they may. Redacted in logs;
    audit log stores hash only."""

    PII_DIRECT = "pii_direct"
    """Direct personal identifiers: full name, exact birth date, address.
    Redacted in logs; audit log stores hash only; webhook payloads redacted
    by default unless tenant opts in."""

    EDUCATIONAL = "educational"
    """Educational records under FERPA: grades, subjects, conduct,
    enrollment. Encrypted at rest; redacted in logs; access logged in the
    FERPA disclosure log."""

    SENSITIVE = "sensitive"
    """GDPR Article 9 special-category data: religion, ethics, philosophical
    beliefs. Excluded from extraction by default; opt-in only with
    documented lawful basis; separate DEK; 30-day hard cap."""

    def is_sensitive(self) -> bool:
        """True iff this class requires redaction in default log output."""
        return self in {
            PIIClass.PII_QUASI,
            PIIClass.PII_DIRECT,
            PIIClass.EDUCATIONAL,
            PIIClass.SENSITIVE,
        }

    def redaction_marker(self) -> str:
        """The marker substituted for a redacted value in log output."""
        return f"[REDACTED:{self.value.upper()}]"


__all__ = ["PIIClass"]
