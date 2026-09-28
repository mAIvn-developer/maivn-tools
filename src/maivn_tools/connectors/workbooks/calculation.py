"""Cache the supported internal formula grammar without executing formula text.

The editable formulas remain authoritative. Cycles or work exceeding the bounded
calculation budget remain uncached for the client spreadsheet engine to handle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import range_boundaries

from .formulas import validate_formula

if TYPE_CHECKING:
    from openpyxl.formula.tokenizer import Token
    from openpyxl.workbook.workbook import Workbook


class CalculationUnavailableError(Exception):
    """Leave results to Excel when a bounded calculation cannot complete."""


@dataclass(frozen=True)
class CellError:
    """An Excel error value, retained rather than converted to a number."""

    code: str


Scalar = float | int | str | bool | None | CellError


@dataclass(frozen=True)
class ReferenceValues:
    """References retain their distinction from literal function arguments."""

    values: tuple[Scalar, ...]


Value = Scalar | ReferenceValues


class FormulaError(Exception):
    """Propagate ordinary spreadsheet arithmetic and reference errors."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _scalar(value: Value) -> Scalar:
    if isinstance(value, ReferenceValues):
        if len(value.values) != 1:
            raise CalculationUnavailableError
        value = value.values[0]
    if isinstance(value, CellError):
        raise FormulaError(value.code)
    return value


def _number(value: Value) -> float:
    scalar = _scalar(value)
    try:
        number = 0.0 if scalar is None else float(cast('str | float', scalar))
        if not math.isfinite(number):
            raise FormulaError('#VALUE!')
        return number
    except (TypeError, ValueError) as exc:
        raise FormulaError('#VALUE!') from exc


def _aggregate(name: str, arguments: list[Value]) -> float:
    numbers: list[float] = []
    for argument in arguments:
        if isinstance(argument, ReferenceValues):
            for value in argument.values:
                if isinstance(value, CellError) and name != 'COUNT':
                    raise FormulaError(value.code)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numbers.append(float(value))
        else:
            numbers.append(_number(argument))
    if name == 'COUNT':
        return float(len(numbers))
    if name == 'SUM':
        return sum(numbers)
    if name == 'AVERAGE':
        if not numbers:
            raise FormulaError('#DIV/0!')
        return sum(numbers) / len(numbers)
    if name == 'MIN':
        return min(numbers, default=0.0)
    if name == 'MAX':
        return max(numbers, default=0.0)
    raise CalculationUnavailableError


class WorkbookCalculator:
    """Resolve forward and cross-sheet dependencies with bounded memoization."""

    def __init__(self, workbook: Workbook) -> None:
        self.workbook = workbook
        self.results: dict[tuple[str, str], Scalar] = {}
        self.active: set[tuple[str, str]] = set()
        self.remaining = 100_000
        self.sheets = {sheet.title.casefold(): sheet.title for sheet in workbook}

    def cell(self, sheet: str, address: str) -> Scalar:
        """Calculate a cell once; never invent a cached value for a cycle."""
        title = self.sheets.get(sheet.casefold())
        if title is None:
            return CellError('#REF!')
        address = address.replace('$', '').upper()
        key = (title, address)
        if key in self.results:
            return self.results[key]
        if key in self.active or len(self.active) >= 128 or self.remaining <= 0:
            raise CalculationUnavailableError
        self.remaining -= 1
        cell = self.workbook[title][address]
        value = cast('Scalar', cell.value)
        if cell.data_type == 'e':
            value = CellError(str(value))
        if cell.data_type == 'f' and isinstance(value, str):
            self.active.add(key)
            try:
                validate_formula(value)
                value = _scalar(_Expression(value, title, self).parse())
                if value is None:
                    value = 0
                if isinstance(value, float) and not math.isfinite(value):
                    value = CellError('#NUM!')
            except FormulaError as exc:
                value = CellError(exc.code)
            except (ZeroDivisionError, OverflowError) as exc:
                value = CellError('#DIV/0!' if isinstance(exc, ZeroDivisionError) else '#NUM!')
            except RecursionError as exc:
                raise CalculationUnavailableError from exc
            finally:
                self.active.remove(key)
        self.results[key] = value
        return value

    def reference(self, source: str, current_sheet: str) -> ReferenceValues:
        """Resolve supported A1 rectangles, including quoted worksheet names."""
        sheet = current_sheet
        if '!' in source:
            sheet, _, source = source.rpartition('!')
            if sheet.startswith("'"):
                sheet = sheet[1:-1].replace("''", "'")
        bounds = range_boundaries(source.replace('$', '').upper())
        left, top, right, bottom = cast('tuple[int, int, int, int]', bounds)
        left, right = sorted((left, right))
        top, bottom = sorted((top, bottom))
        if (right - left + 1) * (bottom - top + 1) > self.remaining:
            raise CalculationUnavailableError
        title = self.sheets.get(sheet.casefold())
        if title is None:
            return ReferenceValues((CellError('#REF!'),))
        cells = self.workbook[title].iter_rows(
            min_row=top, max_row=bottom, min_col=left, max_col=right
        )
        return ReferenceValues(
            tuple(self.cell(title, cell.coordinate) for row in cells for cell in row)
        )


class _Expression:
    def __init__(self, formula: str, sheet: str, calculator: WorkbookCalculator) -> None:
        self.tokens: list[Token] = [
            item for item in Tokenizer(formula).items if item.type != 'WHITE-SPACE'
        ]
        if len(self.tokens) > 512:
            raise CalculationUnavailableError
        self.index = 0
        self.sheet = sheet
        self.calculator = calculator

    def parse(self) -> Value:
        value = self.expression()
        if self.index != len(self.tokens):
            raise CalculationUnavailableError
        return value

    def expression(self, minimum: int = 0) -> Value:
        token = self.tokens[self.index]
        self.index += 1
        if token.type == 'OPERATOR-PREFIX':
            value: Value = _number(self.expression(50)) * (-1 if token.value == '-' else 1)
        elif token.type == 'OPERAND':
            value = (
                float(token.value)
                if token.subtype == 'NUMBER'
                else self.calculator.reference(token.value, self.sheet)
            )
        elif token.type == 'PAREN':
            value = self.expression()
            self.index += 1
        elif token.type == 'FUNC':
            arguments = [self.expression()]
            while self.tokens[self.index].type == 'SEP':
                self.index += 1
                arguments.append(self.expression())
            self.index += 1
            value = _aggregate(token.value[:-1].upper(), arguments)
        else:
            raise CalculationUnavailableError
        while self.index < len(self.tokens):
            token = self.tokens[self.index]
            if token.type == 'OPERATOR-POSTFIX' and minimum <= 60:
                self.index += 1
                value = _number(value) / 100
                continue
            precedence = {'+': 20, '-': 20, '*': 30, '/': 30, '^': 40}.get(token.value, -1)
            if token.type != 'OPERATOR-INFIX' or precedence < minimum:
                break
            self.index += 1
            right = _number(self.expression(precedence + 1))
            left = _number(value)
            if token.value == '+':
                value = left + right
            elif token.value == '-':
                value = left - right
            elif token.value == '*':
                value = left * right
            elif token.value == '/':
                value = left / right
            else:
                try:
                    value = math.pow(left, right)
                except ValueError as exc:
                    raise FormulaError('#NUM!') from exc
        return value
