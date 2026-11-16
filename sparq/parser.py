"""Recursive-descent parsing of Sparq expressions.

M3 Task 02 exposes parse_expression_only(), which requires EOF after one
expression. Full program/statement parsing will be added in M3 Task 03.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from sparq.ast_nodes import (
    ArrayAccess, BinaryExpr, CallExpr, Expr, LiteralExpr, SourceSpan,
    UnaryExpr, VarRef,
)
from sparq.token import Token, TokenType


LITERALS = frozenset({
    TokenType.INT_LITERAL, TokenType.FLOAT_LITERAL, TokenType.CHAR_LITERAL,
    TokenType.STRING_LITERAL, TokenType.TRUE, TokenType.FALSE,
})
COMPARISONS = frozenset({
    TokenType.LESS, TokenType.GREATER,
    TokenType.LESS_EQUAL, TokenType.GREATER_EQUAL,
})
EQUALITY = frozenset({TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL})
MAX_NESTING = 64  # Parser resource guard, not a Sparq language restriction.


@dataclass(eq=False)
class ParseError(Exception):
    category: str
    expected: str
    actual: Token
    explanation: str

    @property
    def line(self) -> int:
        return self.actual.line

    @property
    def column(self) -> int:
        return self.actual.column

    def __str__(self) -> str:
        lexeme = self.actual.lexeme
        if isinstance(lexeme, str):
            preview = lexeme if len(lexeme) <= 40 else lexeme[:20] + "..."
        else:
            preview = "<invalid lexeme>"
        kind = self.actual.type.name if isinstance(self.actual.type, TokenType) else "<invalid type>"
        try:
            position = f"{self.line}:{self.column}"
        except ValueError:  # Malformed, enormous manually supplied coordinates.
            position = "<invalid position>"
        return (
            f"{self.category} at {position}: "
            f"expected {self.expected}, found {kind} "
            f"{preview!r}; {self.explanation}"
        )


class Parser:
    def __init__(self, tokens: list[Token] | tuple[Token, ...]):
        try:
            self.tokens = tuple(tokens)
        except TypeError:
            self.tokens = ()
        self.index = 0
        self._nesting = 0
        self._validate_stream()

    def _validate_stream(self) -> None:
        if not self.tokens:
            self._fail("INVALID_TOKEN_STREAM", "one final EOF token", self._synthetic_eof())
        for index, token in enumerate(self.tokens):
            if not isinstance(token, Token):
                self._fail("INVALID_TOKEN_STREAM", "Token objects", self._synthetic_eof())
            if not isinstance(token.type, TokenType):
                self._fail("INVALID_TOKEN_STREAM", "valid TokenType values", token)
            if not self._valid_position(token):
                self._fail("INVALID_TOKEN_STREAM", "valid source positions", self._synthetic_eof())
            if not isinstance(token.lexeme, str):
                self._fail("INVALID_TOKEN_STREAM", "a string lexeme", token)
            if not self._valid_payload(token):
                self._fail("INVALID_TOKEN_STREAM", "a valid decoded token value", token)
            if token.type is TokenType.EOF and index != len(self.tokens) - 1:
                self._fail("INVALID_TOKEN_STREAM", "EOF only at the end", token)
        if self.tokens[-1].type is not TokenType.EOF:
            self._fail("INVALID_TOKEN_STREAM", "one final EOF token", self._synthetic_eof())
        if self.tokens[-1].lexeme:
            self._fail("INVALID_TOKEN_STREAM", "empty final EOF token", self.tokens[-1])

    @staticmethod
    def _valid_position(token: Token) -> bool:
        positions = (token.line, token.column, token.end_line, token.end_column)
        return (all(type(position) is int and position >= 1 for position in positions)
                and (token.end_line, token.end_column) >= (token.line, token.column))

    @staticmethod
    def _valid_payload(token: Token) -> bool:
        kind, value = token.type, token.literal
        if kind is TokenType.INT_LITERAL:
            return type(value) is int
        if kind is TokenType.FLOAT_LITERAL:
            return type(value) is float and math.isfinite(value)
        if kind is TokenType.CHAR_LITERAL:
            return (isinstance(value, str) and len(value) == 1
                    and not 0xD800 <= ord(value) <= 0xDFFF)
        if kind is TokenType.STRING_LITERAL:
            return isinstance(value, str)
        if kind is TokenType.TRUE:
            return value is True
        if kind is TokenType.FALSE:
            return value is False
        if kind is TokenType.IDENTIFIER:
            return value is None and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token.lexeme) is not None
        return value is None

    def _synthetic_eof(self) -> Token:
        if self.tokens and isinstance(self.tokens[-1], Token) and self._valid_position(self.tokens[-1]):
            last = self.tokens[-1]
            line, column = last.end_line, last.end_column
        else:
            line, column = 1, 1
        return Token(TokenType.EOF, "", None, line, column, line, column)

    def _fail(self, category: str, expected: str, actual: Token | None = None) -> None:
        raise ParseError(
            category, expected, self.peek() if actual is None else actual,
            "Unexpected token in Sparq expression",
        )

    def peek(self) -> Token:
        return self.tokens[min(self.index, len(self.tokens) - 1)]

    def check(self, kind: TokenType) -> bool:
        return self.peek().type is kind

    def is_at_end(self) -> bool:
        return self.check(TokenType.EOF)

    def advance(self) -> Token:
        token = self.peek()
        if not self.is_at_end():
            self.index += 1
        return token

    def match(self, *kinds: TokenType) -> Token | None:
        if self.peek().type in kinds:
            return self.advance()
        return None

    def consume(self, kind: TokenType) -> Token:
        token = self.match(kind)
        if token is None:
            self._fail("EXPECTED_TOKEN", kind.name)
        return token

    def _previous(self) -> Token:
        return self.tokens[max(0, self.index - 1)]

    @staticmethod
    def _span(start: Token, end: Token) -> SourceSpan:
        return SourceSpan(start.line, start.column, end.end_line, end.end_column)

    def _enter_nested(self) -> None:
        self._nesting += 1
        if self._nesting > MAX_NESTING:
            self._fail("RESOURCE_LIMIT", "shallower expression nesting")

    def parse_expression_only(self) -> Expr:
        """Parse one expression and require the stream's final EOF token."""
        try:
            expression = self._parse_expression()
            self.consume(TokenType.EOF)
            return expression
        except RecursionError:
            self._fail("RESOURCE_LIMIT", "shallower expression nesting")

    def _parse_expression(self) -> Expr:
        return self._parse_or()

    def _parse_or(self) -> Expr:
        start = self.peek()
        left = self._parse_and()
        while operator := self.match(TokenType.OR):
            right = self._parse_and()
            left = BinaryExpr(operator.type, left, right, self._span(start, self._previous()))
        return left

    def _parse_and(self) -> Expr:
        start = self.peek()
        left = self._parse_equality()
        while operator := self.match(TokenType.AND):
            right = self._parse_equality()
            left = BinaryExpr(operator.type, left, right, self._span(start, self._previous()))
        return left

    def _parse_equality(self) -> Expr:
        start = self.peek()
        left = self._parse_comparison()
        if self.peek().type in EQUALITY:
            operator = self.advance()
            right = self._parse_comparison()
            return BinaryExpr(operator.type, left, right, self._span(start, self._previous()))
        return left

    def _parse_comparison(self) -> Expr:
        start = self.peek()
        left = self._parse_add()
        if self.peek().type in COMPARISONS:
            operator = self.advance()
            right = self._parse_add()
            return BinaryExpr(operator.type, left, right, self._span(start, self._previous()))
        return left

    def _parse_add(self) -> Expr:
        start = self.peek()
        left = self._parse_mul()
        while operator := self.match(TokenType.PLUS, TokenType.MINUS):
            right = self._parse_mul()
            left = BinaryExpr(operator.type, left, right, self._span(start, self._previous()))
        return left

    def _parse_mul(self) -> Expr:
        start = self.peek()
        left = self._parse_unary()
        while operator := self.match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            right = self._parse_unary()
            left = BinaryExpr(operator.type, left, right, self._span(start, self._previous()))
        return left

    def _parse_unary(self) -> Expr:
        operator = self.match(TokenType.NOT, TokenType.MINUS)
        if operator is None:
            return self._parse_primary()
        self._enter_nested()
        try:
            operand = self._parse_unary()
        finally:
            self._nesting -= 1
        return UnaryExpr(operator.type, operand, self._span(operator, self._previous()))

    def _parse_primary(self) -> Expr:
        token = self.peek()
        if token.type in LITERALS:
            self.advance()
            return LiteralExpr(
                token.type, token.literal, token.lexeme, SourceSpan.from_token(token)
            )
        if token.type is TokenType.IDENTIFIER:
            self.advance()
            if self.match(TokenType.LPAREN):
                args = self._parse_arguments()
                end = self.consume(TokenType.RPAREN)
                return CallExpr(token.lexeme, args, self._span(token, end))
            if self.match(TokenType.LBRACKET):
                index = self._parse_nested_expression()
                end = self.consume(TokenType.RBRACKET)
                return ArrayAccess(token.lexeme, index, self._span(token, end))
            return VarRef(token.lexeme, SourceSpan.from_token(token))
        if self.match(TokenType.LPAREN):
            expression = self._parse_nested_expression()
            self.consume(TokenType.RPAREN)
            # Grouping affects precedence but has no separate AST node. The
            # inner node retains its own span; enclosing nodes use tokens.
            return expression
        self._fail("EXPECTED_EXPRESSION", "an expression", token)

    def _parse_nested_expression(self) -> Expr:
        self._enter_nested()
        try:
            return self._parse_expression()
        finally:
            self._nesting -= 1

    def _parse_arguments(self) -> tuple[Expr, ...]:
        if self.check(TokenType.RPAREN):
            return ()
        args = [self._parse_nested_expression()]
        while self.match(TokenType.COMMA):
            args.append(self._parse_nested_expression())
        return tuple(args)
