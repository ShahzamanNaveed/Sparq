"""Controlled source diagnostics for lexical and semantic analysis."""

from dataclasses import dataclass

from sparq.ast_nodes import SourceSpan


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


@dataclass(eq=False)
class SemanticError(Exception):
    """A fail-fast source diagnostic from a semantic infrastructure operation."""

    category: str
    message: str
    span: SourceSpan
    name: str | None = None
    expected: str | None = None
    actual: str | None = None

    @property
    def line(self) -> int:
        return self.span.start_line

    @property
    def column(self) -> int:
        return self.span.start_column

    def __str__(self) -> str:
        name = f" for {self.name!r}" if self.name is not None else ""
        types = (
            f" (expected {self.expected}, found {self.actual})"
            if self.expected is not None or self.actual is not None else ""
        )
        return f"{self.category} at {self.line}:{self.column}{name}: {self.message}{types}"
