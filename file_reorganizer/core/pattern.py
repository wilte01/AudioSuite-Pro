"""
Pattern parser and evaluator for foobar2000-like template syntax.

Supports:
  $set(name, expr)            -- assign expression result to a named variable
  $if(cond, then_val, else_val) -- conditional branching
  $if2(a, b, ...)             -- first non-empty value
  $eq(a, b)                   -- string equality comparison
  $swapprefix(val, ...prefixes) -- move leading prefix to end
  $left(val, n)               -- first n characters
  $num(val, digits)           -- zero-pad number to width
  %tag_name%                  -- read tag value from audio file
"""

from __future__ import annotations

import os
import re


class PatternError(Exception):
    """Raised when a pattern string cannot be parsed or evaluated."""


_TOKEN_RE = re.compile(
    r"""
    (\$[a-zA-Z_]\w*)           # function name: $set, $if, etc.
    |\(                        # opening paren
    |\)                        # closing paren
    |,                         # comma separator
    |%([a-zA-Z_]\w*)%          # tag reference: %albumartist%
    |("[^"]*")                 # double-quoted string
    |('[^']*')                 # single-quoted string
    |([^$(),%]+)               # literal text
    """,
    re.VERBOSE,
)


def _tokenize(pattern: str) -> list[tuple[str, str]]:
    """Yield (type, value) tokens from *pattern*.

    Token types: FUNC, LPAREN, RPAREN, COMMA, TAG, STRING, LITERAL.
    """
    tokens: list[tuple[str, str]] = []
    for m in _TOKEN_RE.finditer(pattern):
        if m.group(1):  # function name
            tokens.append(("FUNC", m.group(1)))
        elif m.group(2):  # tag reference
            tokens.append(("TAG", m.group(2)))
        elif m.group(3):  # double-quoted string
            tokens.append(("STRING", m.group(3)[1:-1]))
        elif m.group(4):  # single-quoted string
            tokens.append(("STRING", m.group(4)[1:-1]))
        elif m.group(5):  # literal text
            tokens.append(("LITERAL", m.group(5)))
        else:
            ch = pattern[m.start()]
            if ch == "(":
                tokens.append(("LPAREN", "("))
            elif ch == ")":
                tokens.append(("RPAREN", ")"))
            elif ch == ",":
                tokens.append(("COMMA", ","))
            elif ch in " \t":
                tokens.append(("LITERAL", ch))
    return tokens


class _PatternEvaluator:
    """Evaluates a tokenized foobar2000-like pattern against tag values."""

    def __init__(self, tags: dict[str, str]) -> None:
        self._tags = tags
        self._variables: dict[str, str] = {}
        self._pos = 0

    def evaluate(self, tokens: list[tuple[str, str]]) -> str:
        self._pos = 0
        self._tokens = tokens
        parts: list[str] = []
        while self._pos < len(self._tokens):
            parts.append(self._eval_expr())
        return "".join(parts)

    def _peek(self) -> tuple[str, str] | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _advance(self) -> tuple[str, str]:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, *types: str) -> tuple[str, str]:
        tok = self._peek()
        if not tok or tok[0] not in types:
            got = tok[0] if tok else "EOF"
            raise PatternError(f"Expected {types}, got {got}")
        return self._advance()

    def _read_arg(self) -> str:
        """Read a full argument (multi-token sequence) until comma or rparen
        at depth 0."""
        parts: list[str] = []
        depth = 0
        while self._pos < len(self._tokens):
            tok = self._peek()
            assert tok is not None
            if tok[0] == "LPAREN":
                depth += 1
                parts.append(self._advance()[1])
            elif tok[0] == "RPAREN":
                if depth == 0:
                    break
                depth -= 1
                parts.append(self._advance()[1])
            elif tok[0] == "COMMA" and depth == 0:
                break
            else:
                parts.append(self._eval_atom())
        return "".join(parts)

    def _eval_atom(self) -> str:
        tok = self._peek()
        if not tok:
            return ""
        if tok[0] == "FUNC":
            return self._eval_func()
        if tok[0] == "TAG":
            self._advance()
            name = tok[1]
            if name in self._variables:
                return self._variables[name]
            return self._tags.get(name, "")
        if tok[0] == "STRING":
            self._advance()
            return tok[1]
        if tok[0] == "LITERAL":
            self._advance()
            return tok[1]
        self._advance()
        return ""

    def _eval_expr(self) -> str:
        tok = self._peek()
        if not tok:
            return ""
        if tok[0] == "FUNC":
            return self._eval_func()
        if tok[0] == "TAG":
            self._advance()
            name = tok[1]
            if name in self._variables:
                return self._variables[name]
            return self._tags.get(name, "")
        if tok[0] == "STRING":
            self._advance()
            return tok[1]
        if tok[0] == "LITERAL":
            self._advance()
            return tok[1]
        self._advance()
        return ""

    def _eval_func(self) -> str:
        name = self._advance()[1]
        self._expect("LPAREN")

        if name == "$set":
            var_name = self._read_arg().strip()
            self._expect("COMMA")
            value = self._read_arg()
            self._variables[var_name] = value
            self._expect("RPAREN")
            return ""

        if name == "$if":
            cond = self._read_arg()
            self._expect("COMMA")
            then_val = self._read_arg()
            else_val = ""
            tok_check = self._peek()
            if tok_check and tok_check[0] == "COMMA":
                self._advance()
                else_val = self._read_arg()
            self._expect("RPAREN")
            return then_val if (cond and cond != "0") else else_val

        if name == "$if2":
            args: list[str] = []
            args.append(self._read_arg())
            tok_check = self._peek()
            while tok_check and tok_check[0] == "COMMA":
                self._advance()
                args.append(self._read_arg())
                tok_check = self._peek()
            self._expect("RPAREN")
            for a in args:
                if a:
                    return a
            return ""

        if name == "$eq":
            a = self._read_arg()
            self._expect("COMMA")
            b = self._read_arg()
            self._expect("RPAREN")
            return "1" if a == b else "0"

        if name == "$swapprefix":
            val = self._read_arg()
            prefixes: list[str] = []
            tok_check = self._peek()
            while tok_check and tok_check[0] == "COMMA":
                self._advance()
                prefixes.append(self._read_arg())
                tok_check = self._peek()
            self._expect("RPAREN")
            prefixes.sort(key=len, reverse=True)
            for p in prefixes:
                if val.lower().startswith(p.lower()):
                    rest = val[len(p) :].strip()
                    if rest:
                        return f"{rest}, {p}"
            return val

        if name == "$left":
            val = self._read_arg()
            self._expect("COMMA")
            count_str = self._read_arg()
            self._expect("RPAREN")
            try:
                count = int(count_str)
            except ValueError:
                raise PatternError(f"$left requires integer, got {count_str!r}")
            return val[:count]

        if name == "$num":
            val = self._read_arg()
            self._expect("COMMA")
            digits_str = self._read_arg()
            self._expect("RPAREN")
            try:
                digits = int(digits_str)
                num = int(float(val))
            except ValueError:
                return val
            return str(num).zfill(digits)

        if name == "$replace":
            val = self._read_arg()
            self._expect("COMMA")
            old = self._read_arg()
            self._expect("COMMA")
            new = self._read_arg()
            self._expect("RPAREN")
            return val.replace(old, new)

        if name == "$lower":
            val = self._read_arg()
            self._expect("RPAREN")
            return val.lower()

        if name == "$upper":
            val = self._read_arg()
            self._expect("RPAREN")
            return val.upper()

        raise PatternError(f"Unknown function: {name}")


# Public API


def evaluate_pattern(pattern: str, tags: dict[str, str]) -> str:
    """Evaluate a foobar2000-like *pattern* using *tags* and return the result.

    Args:
        pattern: Pattern string with $functions and %tag% references.
        tags: Dict mapping tag field names to their string values.

    Returns:
        The evaluated output string.

    Raises:
        PatternError: If the pattern is malformed.
    """
    tokens = _tokenize(pattern)
    evaluator = _PatternEvaluator(tags)
    return evaluator.evaluate(tokens)


def resolve_path(
    pattern: str,
    tags: dict[str, str],
    base_dir: str = "",
) -> str:
    """Evaluate *pattern* and build a safe filesystem path from the result.

    Path-illegal characters (``<>:"|?*``) are replaced with underscores.
    Empty path components are collapsed.

    Args:
        pattern: The folder/file pattern string.
        tags: Tag values.
        base_dir: Optional root directory to prepend.

    Returns:
        A sanitized absolute or relative path string.
    """
    raw = evaluate_pattern(pattern, tags)
    # Remove control characters (never valid in paths)
    raw = re.sub(r"[\r\n]+", "", raw)
    # Replace path-illegal characters
    raw = re.sub(r'[<>:"|?*]', "_", raw)
    raw = re.sub(r"[/\\]+", lambda _: os.sep, raw)
    # Strip leading/trailing separators
    raw = raw.strip(os.sep)
    # Strip whitespace from each component and drop empties
    components = [c.strip() for c in raw.split(os.sep) if c.strip()]
    raw = os.sep.join(components)
    if base_dir:
        return os.path.join(base_dir, raw)
    return raw
