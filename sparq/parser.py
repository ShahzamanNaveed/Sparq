"""Recursive-descent parsing of Sparq programs and expressions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import math
import re

from sparq.ast_nodes import (
    ArrayAccess, ArrayDecl, AssignStmt, BinaryExpr, Block, CallExpr, CallStmt,
    CaseClause, DoWhileStmt, Expr, ForStmt, FunctionDecl, LiteralExpr,
    Parameter, Program, ReadStmt, ReturnStmt, ScalarDecl, SelectStmt,
    ShowStmt, SourceSpan, Stmt, UnaryExpr, VarRef, WhenStmt, WhileStmt,
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
TYPES = frozenset({
    TokenType.INT, TokenType.FLOAT, TokenType.CHAR, TokenType.STRING, TokenType.BOOL,
})
MAX_NESTING = 64  # Parser resource guard, not a Sparq language restriction.


def _resource_limited(method):
    """Translate host recursion exhaustion at the outermost public entry."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        outermost = self._entry_depth == 0
        self._entry_depth += 1
        try:
            return method(self, *args, **kwargs)
        except RecursionError:
            if outermost:
                self._fail("RESOURCE_LIMIT", "shallower parser nesting")
            raise
        finally:
            self._entry_depth -= 1

    return guarded


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
        self._entry_depth = 0
        self._validate_stream()

    def _validate_stream(self) -> None:
        if not self.tokens:
            self._fail("INVALID_TOKEN_STREAM", "one final EOF token", self._synthetic_eof())
        previous_end = None
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
            if previous_end is not None and (token.line, token.column) < previous_end:
                self._fail(
                    "INVALID_TOKEN_STREAM", "token start at or after previous token end", token
                )
            previous_end = (token.end_line, token.end_column)
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
            "Unexpected token in Sparq syntax",
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

    @_resource_limited
    def parse(self) -> Program:
        """Parse a complete program: functions, one START block, then EOF."""
        start = self.peek()
        functions = []
        while self.check(TokenType.FUNC):
            functions.append(self._parse_function())
        self.consume(TokenType.START)
        main = self.parse_block()
        end = self._previous()
        self.consume(TokenType.EOF)
        return Program(tuple(functions), main, self._span(start, end))

    def _parse_type(self) -> Token:
        if self.peek().type not in TYPES:
            self._fail("EXPECTED_TOKEN", "a scalar type")
        return self.advance()

    def _parse_function(self) -> FunctionDecl:
        start = self.consume(TokenType.FUNC)
        name = self.consume(TokenType.IDENTIFIER)
        self.consume(TokenType.LPAREN)
        params = []
        if self.peek().type in TYPES:
            params.append(self._parse_parameter())
            while self.match(TokenType.COMMA):
                params.append(self._parse_parameter())
        self.consume(TokenType.RPAREN)
        self.consume(TokenType.ARROW)
        if self.check(TokenType.VOID):
            return_type = self.advance()
        else:
            return_type = self._parse_type()
        body = self.parse_block()
        return FunctionDecl(
            name.lexeme, tuple(params), return_type.type, body,
            self._span(start, self._previous()),
        )

    def _parse_parameter(self) -> Parameter:
        type_token = self._parse_type()
        name = self.consume(TokenType.IDENTIFIER)
        return Parameter(type_token.type, name.lexeme, self._span(type_token, name))

    @_resource_limited
    def parse_block(self) -> Block:
        """Parse a braced list of statements, including nested blocks."""
        start = self.consume(TokenType.LBRACE)
        statements = []
        while not self.check(TokenType.RBRACE):
            if self.is_at_end():
                self._fail("EXPECTED_TOKEN", TokenType.RBRACE.name)
            statements.append(self.parse_statement())
        end = self.consume(TokenType.RBRACE)
        return Block(tuple(statements), self._span(start, end))

    @_resource_limited
    def parse_statement(self) -> Stmt:
        """Parse one statement according to its leading token."""
        kind = self.peek().type
        if kind in TYPES:
            return self._parse_declaration()
        if kind is TokenType.IDENTIFIER:
            return self._parse_identifier_statement()
        if kind is TokenType.WHEN:
            return self._parse_when()
        if kind is TokenType.SELECT:
            return self._parse_select()
        if kind is TokenType.REPEAT:
            return self._parse_repeat()
        if kind is TokenType.WHILE:
            return self._parse_while()
        if kind is TokenType.DO:
            return self._parse_do_while()
        if kind is TokenType.SHOW:
            return self._parse_show()
        if kind is TokenType.READ:
            return self._parse_read()
        if kind is TokenType.RETURN:
            return self._parse_return()
        if kind is TokenType.LBRACE:
            return self.parse_block()
        self._fail("EXPECTED_STATEMENT", "a statement")

    def _parse_declaration(self) -> ScalarDecl | ArrayDecl:
        type_token = self._parse_type()
        name = self.consume(TokenType.IDENTIFIER)
        if self.match(TokenType.LBRACKET):
            size_token = self.consume(TokenType.INT_LITERAL)
            size = LiteralExpr(
                size_token.type, size_token.literal, size_token.lexeme,
                SourceSpan.from_token(size_token),
            )
            self.consume(TokenType.RBRACKET)
            initializers = None
            if self.match(TokenType.EQUAL):
                self.consume(TokenType.LBRACE)
                initializers = self._parse_expression_list()  # Nonempty <arguments>.
                self.consume(TokenType.RBRACE)
            end = self.consume(TokenType.SEMICOLON)
            return ArrayDecl(
                type_token.type, name.lexeme, size, initializers,
                self._span(type_token, end),
            )
        initializer = self._parse_expression() if self.match(TokenType.EQUAL) else None
        end = self.consume(TokenType.SEMICOLON)
        return ScalarDecl(
            type_token.type, name.lexeme, initializer, self._span(type_token, end)
        )

    def _parse_target_after_name(self, name: Token) -> VarRef | ArrayAccess:
        if self.match(TokenType.LBRACKET):
            index = self._parse_expression()
            end = self.consume(TokenType.RBRACKET)
            return ArrayAccess(name.lexeme, index, self._span(name, end))
        return VarRef(name.lexeme, SourceSpan.from_token(name))

    def _parse_assignment_core(self) -> AssignStmt:
        name = self.consume(TokenType.IDENTIFIER)
        return self._parse_assignment_after_name(name)

    def _parse_assignment_after_name(self, name: Token) -> AssignStmt:
        target = self._parse_target_after_name(name)
        self.consume(TokenType.EQUAL)
        value = self._parse_expression()
        return AssignStmt(target, value, self._span(name, self._previous()))

    def _parse_identifier_statement(self) -> AssignStmt | CallStmt:
        name = self.consume(TokenType.IDENTIFIER)
        if self.match(TokenType.LPAREN):
            args = self._parse_arguments()
            close = self.consume(TokenType.RPAREN)
            call = CallExpr(name.lexeme, args, self._span(name, close))
            end = self.consume(TokenType.SEMICOLON)
            return CallStmt(call, self._span(name, end))
        statement = self._parse_assignment_after_name(name)
        end = self.consume(TokenType.SEMICOLON)
        return AssignStmt(statement.target, statement.value, self._span(name, end))

    def _parse_when(self) -> WhenStmt:
        start = self.consume(TokenType.WHEN)
        self.consume(TokenType.LPAREN)
        condition = self._parse_expression()
        self.consume(TokenType.RPAREN)
        then_block = self.parse_block()
        else_block = self.parse_block() if self.match(TokenType.OTHERWISE) else None
        return WhenStmt(condition, then_block, else_block,
                        self._span(start, self._previous()))

    def _parse_case_label(self) -> LiteralExpr | UnaryExpr:
        minus = self.match(TokenType.MINUS)
        if minus is not None:
            token = self.consume(TokenType.INT_LITERAL)
        elif self.peek().type in (TokenType.INT_LITERAL, TokenType.CHAR_LITERAL,
                                  TokenType.STRING_LITERAL):
            token = self.advance()
        else:
            self._fail("EXPECTED_CASE_LABEL", "an INT, CHAR, or STRING literal")
        literal = LiteralExpr(token.type, token.literal, token.lexeme,
                              SourceSpan.from_token(token))
        return UnaryExpr(TokenType.MINUS, literal, self._span(minus, token)) if minus else literal

    def _parse_select(self) -> SelectStmt:
        start = self.consume(TokenType.SELECT)
        self.consume(TokenType.LPAREN)
        selector = self._parse_expression()
        self.consume(TokenType.RPAREN)
        self.consume(TokenType.LBRACE)
        cases = []
        while self.check(TokenType.CASE):
            case_start = self.advance()
            label = self._parse_case_label()
            self.consume(TokenType.COLON)
            body = self.parse_block()
            cases.append(CaseClause(label, body, self._span(case_start, self._previous())))
        default = None
        if self.match(TokenType.DEFAULT):
            self.consume(TokenType.COLON)
            default = self.parse_block()
        end = self.consume(TokenType.RBRACE)
        return SelectStmt(selector, tuple(cases), default, self._span(start, end))

    def _parse_repeat(self) -> ForStmt:
        start = self.consume(TokenType.REPEAT)
        self.consume(TokenType.LPAREN)
        initializer = None
        if self.peek().type in TYPES:
            type_token = self._parse_type()
            name = self.consume(TokenType.IDENTIFIER)
            self.consume(TokenType.EQUAL)
            value = self._parse_expression()
            initializer = ScalarDecl(type_token.type, name.lexeme, value,
                                     self._span(type_token, self._previous()))
        elif self.check(TokenType.IDENTIFIER):
            initializer = self._parse_assignment_core()
        elif not self.check(TokenType.SEMICOLON):
            self._fail("EXPECTED_TOKEN", "a REPEAT initializer or ';'")
        self.consume(TokenType.SEMICOLON)
        condition = None if self.check(TokenType.SEMICOLON) else self._parse_expression()
        self.consume(TokenType.SEMICOLON)
        update = None
        if self.check(TokenType.IDENTIFIER):
            update = self._parse_assignment_core()
        elif not self.check(TokenType.RPAREN):
            self._fail("EXPECTED_TOKEN", "a REPEAT update or ')'")
        self.consume(TokenType.RPAREN)
        body = self.parse_block()
        return ForStmt(initializer, condition, update, body,
                       self._span(start, self._previous()))

    def _parse_while(self) -> WhileStmt:
        start = self.consume(TokenType.WHILE)
        self.consume(TokenType.LPAREN)
        condition = self._parse_expression()
        self.consume(TokenType.RPAREN)
        body = self.parse_block()
        return WhileStmt(condition, body, self._span(start, self._previous()))

    def _parse_do_while(self) -> DoWhileStmt:
        start = self.consume(TokenType.DO)
        body = self.parse_block()
        self.consume(TokenType.WHILE)
        self.consume(TokenType.LPAREN)
        condition = self._parse_expression()
        self.consume(TokenType.RPAREN)
        end = self.consume(TokenType.SEMICOLON)
        return DoWhileStmt(body, condition, self._span(start, end))

    def _parse_return(self) -> ReturnStmt:
        start = self.consume(TokenType.RETURN)
        value = None if self.check(TokenType.SEMICOLON) else self._parse_expression()
        end = self.consume(TokenType.SEMICOLON)
        return ReturnStmt(value, self._span(start, end))

    def _parse_read(self) -> ReadStmt:
        start = self.consume(TokenType.READ)
        self.consume(TokenType.LPAREN)
        name = self.consume(TokenType.IDENTIFIER)
        target = self._parse_target_after_name(name)
        self.consume(TokenType.RPAREN)
        end = self.consume(TokenType.SEMICOLON)
        return ReadStmt(target, self._span(start, end))

    def _parse_show(self) -> ShowStmt:
        start = self.consume(TokenType.SHOW)
        self.consume(TokenType.LPAREN)
        value = self._parse_expression()
        self.consume(TokenType.RPAREN)
        end = self.consume(TokenType.SEMICOLON)
        return ShowStmt(value, self._span(start, end))

    @_resource_limited
    def parse_expression_only(self) -> Expr:
        """Parse one expression and require the stream's final EOF token."""
        expression = self._parse_expression()
        self.consume(TokenType.EOF)
        return expression

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
        return self._parse_expression_list()

    def _parse_expression_list(self) -> tuple[Expr, ...]:
        args = [self._parse_nested_expression()]
        while self.match(TokenType.COMMA):
            args.append(self._parse_nested_expression())
        return tuple(args)
