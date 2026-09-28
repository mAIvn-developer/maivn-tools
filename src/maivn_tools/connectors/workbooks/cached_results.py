"""Write calculated values and chart caches while retaining all XLSX formulas."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING
from xml.etree import ElementTree
from zipfile import ZipFile

from .calculation import CalculationUnavailableError, CellError, Scalar, WorkbookCalculator

if TYPE_CHECKING:
    from openpyxl.workbook.workbook import Workbook

_SHEET = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_CHART = '{http://schemas.openxmlformats.org/drawingml/2006/chart}'


def _write_value(cell: ElementTree.Element, value: Scalar) -> None:
    node = cell.find(f'{_SHEET}v')
    if node is None:
        node = ElementTree.SubElement(cell, f'{_SHEET}v')
    if isinstance(value, CellError):
        cell.set('t', 'e')
        node.text = value.code
    elif isinstance(value, bool):
        cell.set('t', 'b')
        node.text = '1' if value else '0'
    elif isinstance(value, str):
        cell.set('t', 'str')
        node.text = value
    else:
        cell.set('t', 'n')
        node.text = str(value if value is not None else 0)


def _chart_caches(root: ElementTree.Element, calculator: WorkbookCalculator) -> None:
    for parent in root.iter():
        for reference in list(parent):
            if reference.tag not in {f'{_CHART}numRef', f'{_CHART}strRef'}:
                continue
            formula = reference.findtext(f'{_CHART}f')
            if not formula:
                continue
            try:
                values = calculator.reference(formula, '').values
            except CalculationUnavailableError:
                continue
            text = reference.tag == f'{_CHART}strRef' or (
                parent.tag == f'{_CHART}cat' and any(isinstance(value, str) for value in values)
            )
            kind = 'str' if text else 'num'
            reference.tag = f'{_CHART}{kind}Ref'
            for child in list(reference):
                if child.tag in {f'{_CHART}numCache', f'{_CHART}strCache'}:
                    reference.remove(child)
            cache = ElementTree.SubElement(reference, f'{_CHART}{kind}Cache')
            if not text:
                ElementTree.SubElement(cache, f'{_CHART}formatCode').text = 'General'
            ElementTree.SubElement(cache, f'{_CHART}ptCount', {'val': str(len(values))})
            for index, value in enumerate(values):
                if value is None or isinstance(value, CellError):
                    continue
                if not text and (isinstance(value, (str, bool))):
                    continue
                point = ElementTree.SubElement(cache, f'{_CHART}pt', {'idx': str(index)})
                ElementTree.SubElement(point, f'{_CHART}v').text = str(value)


def cache_results(data: bytes, workbook: Workbook) -> bytes:
    """Populate snapshot caches; clients still recalculate after subsequent edits."""
    calculator = WorkbookCalculator(workbook)
    output = io.BytesIO()
    sheets = {
        f'xl/worksheets/sheet{index}.xml': sheet.title for index, sheet in enumerate(workbook, 1)
    }
    with ZipFile(io.BytesIO(data)) as source, ZipFile(output, 'w') as destination:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename in sheets:
                root = ElementTree.fromstring(content)
                for cell in root.iter(f'{_SHEET}c'):
                    if cell.find(f'{_SHEET}f') is None:
                        continue
                    try:
                        value = calculator.cell(sheets[entry.filename], cell.attrib['r'])
                    except CalculationUnavailableError:
                        continue
                    _write_value(cell, value)
                content = ElementTree.tostring(root, encoding='utf-8')
            elif entry.filename.startswith('xl/charts/chart') and entry.filename.endswith('.xml'):
                root = ElementTree.fromstring(content)
                _chart_caches(root, calculator)
                content = ElementTree.tostring(root, encoding='utf-8')
            destination.writestr(entry, content)
    return output.getvalue()
