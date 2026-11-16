"""Token records produced by the Sparq lexer.

End positions are exclusive: the next source character begins at
(end_line, end_column). Columns count Unicode code points, including tabs.
"""

from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    IDENTIFIER = auto()
    INT_LITERAL = auto()
    FLOAT_LITERAL = auto()
    CHAR_LITERAL = auto()
    STRING_LITERAL = auto()
    START = auto()
    FUNC = auto()
    RETURN = auto()
    INT = auto()
    FLOAT = auto()
    CHAR = auto()
    STRING = auto()
    BOOL = auto()
    VOID = auto()
    WHEN = auto()
    OTHERWISE = auto()
    SELECT = auto()
    CASE = auto()
    DEFAULT = auto()
    REPEAT = auto()
    WHILE = auto()
    DO = auto()
    SHOW = auto()
    READ = auto()
    TRUE = auto()
    FALSE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    GREATER = auto()
    LESS = auto()
    GREATER_EQUAL = auto()
    LESS_EQUAL = auto()
    EQUAL_EQUAL = auto()
    BANG_EQUAL = auto()
    EQUAL = auto()
    ARROW = auto()
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    SEMICOLON = auto()
    COMMA = auto()
    COLON = auto()
    EOF = auto()


@dataclass(frozen=True, slots=True)
class Token:
    type: TokenType
    lexeme: str
    literal: object | None
    line: int
    column: int
    end_line: int
    end_column: int
