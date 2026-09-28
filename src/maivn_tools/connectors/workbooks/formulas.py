"""Validate a deliberately small grammar of internal workbook calculations.

This validates syntax and reference bounds, not calculated results. Excel or
another spreadsheet engine performs calculation when the workbook is opened.
"""

from __future__ import annotations

import math
import re

from openpyxl.formula import Tokenizer
from openpyxl.formula.tokenizer import TokenizerError
from openpyxl.utils.cell import column_index_from_string

_FUNCTIONS = frozenset({'SUM', 'AVERAGE', 'MIN', 'MAX', 'COUNT'})
_CELL = re.compile(r'\$?([A-Za-z]{1,3})\$?([1-9][0-9]{0,6})')
_SHEET = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_.]*|'(?:[^']|'')+')")
_ERROR = 'formula is outside the supported internal calculation grammar'


def _reference(value: str) -> bool:
    if '!' in value:
        sheet, _, value = value.rpartition('!')
        if _SHEET.fullmatch(sheet) is None:
            return False
        decoded = sheet[1:-1].replace("''", "'") if sheet.startswith("'") else sheet
        if len(decoded) > 31 or any(char in decoded for char in '[]:/\\?*'):
            return False
    cells = value.split(':')
    if not 1 <= len(cells) <= 2:
        return False
    for cell in cells:
        match = _CELL.fullmatch(cell)
        if match is None:
            return False
        if column_index_from_string(match[1]) > 16_384 or int(match[2]) > 1_048_576:
            return False
    return True


def validate_formula(formula: str) -> None:
    """Accept internal A1 references, arithmetic and five aggregate functions."""
    if not formula.startswith('=') or not 1 < len(formula) <= 8192:
        raise ValueError(_ERROR)
    try:
        tokens = Tokenizer(formula).items
    except (TokenizerError, IndexError) as exc:
        raise ValueError(_ERROR) from exc
    stack: list[str] = []
    expect_operand = True
    for token in tokens:
        if token.type == 'WHITE-SPACE':
            continue
        if token.type == 'OPERAND' and expect_operand:
            if token.subtype == 'RANGE':
                if not _reference(token.value):
                    raise ValueError(_ERROR)
            elif token.subtype == 'NUMBER':
                try:
                    finite = math.isfinite(float(token.value))
                except ValueError as exc:
                    raise ValueError(_ERROR) from exc
                if not finite:
                    raise ValueError(_ERROR)
            else:
                raise ValueError(_ERROR)
            expect_operand = False
        elif token.type in {'FUNC', 'PAREN'} and token.subtype == 'OPEN' and expect_operand:
            if token.type == 'FUNC' and token.value[:-1].upper() not in _FUNCTIONS:
                raise ValueError(_ERROR)
            stack.append(token.type)
            if len(stack) > 64:
                raise ValueError(_ERROR)
        elif token.type in {'FUNC', 'PAREN'} and token.subtype == 'CLOSE' and not expect_operand:
            if not stack or stack.pop() != token.type:
                raise ValueError(_ERROR)
        elif token.type == 'OPERATOR-PREFIX' and token.value in {'+', '-'} and expect_operand:
            continue
        elif (
            token.type == 'OPERATOR-INFIX'
            and token.value in {'+', '-', '*', '/', '^'}
            and not expect_operand
        ):
            expect_operand = True
        elif token.type == 'OPERATOR-POSTFIX' and token.value == '%' and not expect_operand:
            continue
        elif token.type == 'SEP' and token.subtype == 'ARG' and not expect_operand:
            if not stack or stack[-1] != 'FUNC':
                raise ValueError(_ERROR)
            expect_operand = True
        else:
            raise ValueError(_ERROR)
    if expect_operand or stack:
        raise ValueError(_ERROR)
