"""Manual Sparq lexer using an indexed, in-memory character buffer.

The cursor's peek and peek_next methods provide lookahead without consuming
input. advance updates 1-based positions and treats CRLF as one line break.
"""

from __future__ import annotations

import math
import re
import sys
import unicodedata
from pathlib import Path

from sparq.errors import LexicalError
from sparq.token import Token, TokenType


KEYWORDS = {
    name: TokenType[name]
    for name in (
        "START FUNC RETURN INT FLOAT CHAR STRING BOOL VOID WHEN OTHERWISE "
        "SELECT CASE DEFAULT REPEAT WHILE DO SHOW READ TRUE FALSE AND OR NOT"
    ).split()
}
TWO_CHARACTER = {
    ">=": TokenType.GREATER_EQUAL,
    "<=": TokenType.LESS_EQUAL,
    "==": TokenType.EQUAL_EQUAL,
    "!=": TokenType.BANG_EQUAL,
    "->": TokenType.ARROW,
}
ONE_CHARACTER = {
    "+": TokenType.PLUS,
    "-": TokenType.MINUS,
    "*": TokenType.STAR,
    "/": TokenType.SLASH,
    "%": TokenType.PERCENT,
    ">": TokenType.GREATER,
    "<": TokenType.LESS,
    "=": TokenType.EQUAL,
    "(": TokenType.LPAREN,
    ")": TokenType.RPAREN,
    "{": TokenType.LBRACE,
    "}": TokenType.RBRACE,
    "[": TokenType.LBRACKET,
    "]": TokenType.RBRACKET,
    ";": TokenType.SEMICOLON,
    ",": TokenType.COMMA,
    ":": TokenType.COLON,
}
ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "0": "\0",
}
NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z")


def _letter(ch: str) -> bool:
    return ("A" <= ch <= "Z") or ("a" <= ch <= "z")


def _digit(ch: str) -> bool:
    return "0" <= ch <= "9"


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.index = 0
        self.line = 1
        self.column = 1

    @classmethod
    def from_file(cls, path: str | Path) -> Lexer:
        data = Path(path).read_bytes()
        try:
            source = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            prefix = data[: exc.start].decode("utf-8")
            cursor = cls(prefix)
            while not cursor.is_at_end():
                cursor.advance()
            raise LexicalError(
                "INVALID_ENCODING", "Source file is not valid UTF-8",
                cursor.line, cursor.column, data[exc.start:exc.end].hex()
            ) from None
        return cls(source)

    def is_at_end(self) -> bool:
        return self.index >= len(self.source)

    def peek(self) -> str:
        return "" if self.is_at_end() else self.source[self.index]

    def peek_next(self) -> str:
        i = self.index + 1
        return "" if i >= len(self.source) else self.source[i]

    def advance(self) -> str:
        if self.is_at_end():
            return ""
        ch = self.source[self.index]
        self.index += 1
        if ch == "\r":
            if self.peek() == "\n":
                self.index += 1
                ch = "\r\n"
            self.line += 1
            self.column = 1
        elif ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def _token(
        self, kind: TokenType, start: int, line: int, column: int,
        literal: object | None = None,
    ) -> Token:
        return Token(
            kind, self.source[start:self.index], literal,
            line, column, self.line, self.column,
        )

    def _error(
        self, category: str, message: str, start: int, line: int, column: int,
    ) -> None:
        raise LexicalError(
            category, message, line, column, self.source[start:self.index]
        )

    def _identifier(self, start: int, line: int, column: int) -> Token:
        while _letter(self.peek()) or _digit(self.peek()) or self.peek() == "_":
            self.advance()
        word = self.source[start:self.index]
        kind = KEYWORDS.get(word, TokenType.IDENTIFIER)
        literal = True if kind is TokenType.TRUE else False if kind is TokenType.FALSE else None
        return self._token(kind, start, line, column, literal)

    def _number(self, start: int, line: int, column: int) -> Token:
        # Consume one contiguous number-like sequence, then validate it as a
        # whole. Operators are not part of this run and remain separate tokens.
        while self.peek() and (
            _letter(self.peek()) or _digit(self.peek()) or self.peek() in "._"
        ):
            self.advance()
        lexeme = self.source[start:self.index]
        if not NUMBER.fullmatch(lexeme):
            category = "MALFORMED_FLOAT" if "." in lexeme else "MALFORMED_NUMBER"
            self._error(category, "Malformed numeric literal", start, line, column)
        if "." in lexeme:
            value = float(lexeme)
            if not math.isfinite(value):
                self._error(
                    "NONFINITE_FLOAT", "Float literal is not finite",
                    start, line, column,
                )
            return self._token(TokenType.FLOAT_LITERAL, start, line, column, value)
        # Manual accumulation avoids Python's input-digit limit, preserving
        # Sparq's arbitrary-precision INT literal rule.
        value = 0
        for ch in lexeme:
            value = value * 10 + ord(ch) - ord("0")
        return self._token(TokenType.INT_LITERAL, start, line, column, value)

    def _quoted(self, start: int, line: int, column: int, quote: str) -> Token:
        self.advance()  # opening quote
        decoded: list[str] = []
        kind = TokenType.CHAR_LITERAL if quote == "'" else TokenType.STRING_LITERAL
        label = "character" if quote == "'" else "string"
        while True:
            ch = self.peek()
            if not ch or ch in "\r\n":
                self._error(
                    "UNTERMINATED_CHAR" if quote == "'" else "UNTERMINATED_STRING",
                    f"Unterminated {label} literal", start, line, column,
                )
            if ch == quote:
                self.advance()
                break
            if ch == "\\":
                self.advance()
                escape = self.peek()
                if escape not in ESCAPES:
                    if escape and escape not in "\r\n":
                        self.advance()
                    self._error(
                        "INVALID_ESCAPE", "Unsupported escape sequence",
                        start, line, column,
                    )
                self.advance()
                decoded.append(ESCAPES[escape])
            else:
                if unicodedata.category(ch) == "Cc" or 0xD800 <= ord(ch) <= 0xDFFF:
                    self.advance()
                    self._error(
                        "INVALID_LITERAL_CHARACTER",
                        "Raw control or non-scalar character in literal",
                        start, line, column,
                    )
                decoded.append(self.advance())
        if quote == "'" and len(decoded) != 1:
            self._error(
                "INVALID_CHAR_LENGTH", "Character literal must contain one character",
                start, line, column,
            )
        return self._token(kind, start, line, column, "".join(decoded))

    def _skip_space_or_comment(self) -> bool:
        ch = self.peek()
        if ch in (" ", "\t", "\r", "\n"):
            self.advance()
            return True
        if ch == "/" and self.peek_next() == "/":
            self.advance()
            self.advance()
            while not self.is_at_end() and self.peek() not in "\r\n":
                self.advance()
            return True
        if ch == "/" and self.peek_next() == "*":
            start, line, column = self.index, self.line, self.column
            self.advance()
            self.advance()
            while not self.is_at_end():
                if self.peek() == "*" and self.peek_next() == "/":
                    self.advance()
                    self.advance()
                    return True
                self.advance()
            self._error(
                "UNTERMINATED_COMMENT", "Unterminated block comment",
                start, line, column,
            )
        return False

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while not self.is_at_end():
            if self._skip_space_or_comment():
                continue
            start, line, column = self.index, self.line, self.column
            ch = self.peek()
            if _letter(ch) or ch == "_":
                tokens.append(self._identifier(start, line, column))
            elif _digit(ch):
                tokens.append(self._number(start, line, column))
            elif ch == "." and _digit(self.peek_next()):
                tokens.append(self._number(start, line, column))
            elif ch in ("'", '"'):
                tokens.append(self._quoted(start, line, column, ch))
            elif (pair := ch + self.peek_next()) in TWO_CHARACTER:
                self.advance()
                self.advance()
                tokens.append(self._token(TWO_CHARACTER[pair], start, line, column))
            elif ch in ONE_CHARACTER:
                self.advance()
                tokens.append(self._token(ONE_CHARACTER[ch], start, line, column))
            else:
                self.advance()
                self._error("INVALID_CHARACTER", "Invalid source character", start, line, column)
        tokens.append(Token(TokenType.EOF, "", None, self.line, self.column, self.line, self.column))
        return tokens


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: python -m sparq.lexer SOURCE.spq", file=sys.stderr)
        return 2
    try:
        tokens = Lexer.from_file(args[0]).tokenize()
    except (LexicalError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    for token in tokens:
        if token.type is TokenType.INT_LITERAL and len(token.lexeme) > 80:
            # Formatting a huge Python int can hit the host's digit limit.
            # This affects display only; the token retains its full value.
            preview = token.lexeme[:24] + "..." + token.lexeme[-24:]
            lexeme_display = f"{preview!r} ({len(token.lexeme)} digits)"
            literal_display = f"<INT from {len(token.lexeme)} source digits>"
        else:
            lexeme_display = repr(token.lexeme)
            literal_display = repr(token.literal)
        print(
            f"{token.line}:{token.column}-{token.end_line}:{token.end_column} "
            f"{token.type.name} {lexeme_display} {literal_display}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
