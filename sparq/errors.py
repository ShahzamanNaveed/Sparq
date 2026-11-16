"""Controlled source diagnostics for lexical analysis."""

from dataclasses import dataclass


@dataclass(eq=False)
class LexicalError(Exception):
    category: str
    message: str
    line: int
    column: int
    offending_text: str = ""

    def __str__(self) -> str:
        detail = f" near {self.offending_text!r}" if self.offending_text else ""
        return f"{self.category} at {self.line}:{self.column}: {self.message}{detail}"
