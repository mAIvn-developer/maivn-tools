"""Local artifact benchmark with separate automated, visual and model evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, cast

from . import artifact_quality_documents as documents
from . import artifact_quality_presentations as presentations
from . import artifact_quality_workbooks as workbooks

_FORMATS = ('docx', 'pdf', 'pptx', 'xlsx')


def _mapping(value: object) -> dict[str, Any] | None:
    return cast('dict[str, Any]', value) if isinstance(value, dict) else None


def _checks(value: object) -> bool:
    mapping = _mapping(value)
    return mapping is not None and bool(mapping) and all(item is True for item in mapping.values())


def _artifact(path: object) -> dict[str, str]:
    target = Path(str(path)).resolve()
    return {'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}


def _result(
    extension: str,
    evidence: dict[str, Any],
    initial: object,
    revised: object,
) -> dict[str, Any]:
    checks = evidence.get('checks', {})
    return {
        'automated': {'status': 'pass' if _checks(checks) else 'fail', 'checks': checks},
        'artifacts': {'initial': _artifact(initial), 'revised': _artifact(revised)},
        'native_render': {'status': 'pending'},
        'visual_review': {'status': 'pending'},
        'calculation': {'status': 'pending' if extension == 'xlsx' else 'not_applicable'},
        'evidence': evidence,
    }


def _failed(error: Exception) -> dict[str, Any]:
    return {
        'automated': {'status': 'fail', 'checks': {'evaluator_completed': False}},
        'artifacts': {},
        'native_render': {'status': 'pending'},
        'visual_review': {'status': 'pending'},
        'calculation': {'status': 'not_run'},
        'error': f'{type(error).__name__}: {error}',
    }


def _document_checks(extension: str, evidence: dict[str, Any]) -> dict[str, bool]:
    """Turn inspection observations into explicit expected revision gates."""
    checks: dict[str, bool] = {'fixture_checks_present': _checks(evidence.get('checks'))}
    checks.update(evidence.get('checks', {}))
    for revision in ('initial', 'revised'):
        observed = evidence.get(revision, {})
        for name in ('unicode_preserved', 'table_records_complete', 'table_headers_repeat'):
            checks[f'{revision}_{name}'] = observed.get(name) is True
        checks[f'{revision}_decision_present'] = observed.get(f'{revision}_decision') is True
        other = 'initial' if revision == 'revised' else 'revised'
        checks[f'{revision}_other_decision_absent'] = observed.get(f'{other}_decision') is False
        if extension == 'pdf':
            checks[f'{revision}_text_starts_within_page'] = (
                observed.get('text_starts_within_page') is True
            )
            count = observed.get('page_count')
            checks[f'{revision}_multiple_pages'] = isinstance(count, int) and count > 1
    return checks


def _validate_artifact(extension: str, revision: str, value: object) -> list[str]:
    item = _mapping(value)
    if item is None or not isinstance(item.get('path'), str):
        return [f'{extension}/{revision}: missing artifact path']
    path = Path(item['path'])
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [f'{extension}/{revision}: cannot read artifact: {exc}']
    errors: list[str] = []
    if not raw or path.suffix.lower() != f'.{extension}':
        errors.append(f'{extension}/{revision}: artifact is empty or has the wrong extension')
    if hashlib.sha256(raw).hexdigest() != item.get('sha256'):
        errors.append(f'{extension}/{revision}: sha256 differs from recorded artifact')
    return errors


def validate_report(report: dict[str, Any]) -> list[str]:
    """Fail closed on missing gates/files and verify hashes against current bytes.

    This does not authenticate a reviewer or turn a structural pass into visual
    approval. Native rendering, calculation and live model evidence stay separate.
    """
    errors: list[str] = []
    formats = _mapping(report.get('formats'))
    if formats is None or set(formats) != set(_FORMATS):
        errors.append('expected exactly docx, pdf, pptx and xlsx format results')
    if formats is None:
        return errors
    for extension in _FORMATS:
        result = _mapping(formats.get(extension))
        if result is None:
            errors.append(f'{extension}: missing result')
            continue
        automated = _mapping(result.get('automated'))
        if automated is None or not _checks(automated.get('checks')):
            errors.append(f'{extension}: automated gates must be nonempty and all exactly true')
        artifacts = _mapping(result.get('artifacts'))
        if artifacts is None:
            errors.append(f'{extension}: missing artifacts')
            continue
        for revision in ('initial', 'revised'):
            errors.extend(_validate_artifact(extension, revision, artifacts.get(revision)))
    return errors


def run(output_dir: Path) -> dict[str, Any]:
    """Run local fixtures only, retaining each execution in a fresh output directory."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix='run-', dir=output_dir))
    formats: dict[str, Any] = {}
    try:
        document_evidence = cast('dict[str, Any]', documents.run(run_dir / 'documents'))
        for extension in ('docx', 'pdf'):
            evidence = dict(cast('dict[str, Any]', document_evidence['formats'][extension]))
            evidence['checks'] = _document_checks(extension, evidence)
            formats[extension] = _result(
                extension,
                evidence,
                evidence['paths']['initial'],
                evidence['paths']['revised'],
            )
        document_limitations = cast('list[str]', document_evidence.get('limitations', []))
    except Exception as exc:  # noqa: BLE001 - preserve independent format results on fixture failure
        formats.update({extension: _failed(exc) for extension in ('docx', 'pdf')})
        document_limitations = []
    try:
        slide_evidence = presentations.run(run_dir / 'presentations')
        formats['pptx'] = _result(
            'pptx',
            slide_evidence,
            slide_evidence['initial_path'],
            slide_evidence['revised_path'],
        )
    except Exception as exc:  # noqa: BLE001 - a failed renderer is benchmark evidence
        formats['pptx'] = _failed(exc)
    try:
        workbook_evidence = workbooks.run(run_dir / 'workbooks')
        formats['xlsx'] = _result(
            'xlsx',
            workbook_evidence,
            workbook_evidence['initial'],
            workbook_evidence['revised'],
        )
    except Exception as exc:  # noqa: BLE001 - a failed renderer is benchmark evidence
        formats['xlsx'] = _failed(exc)
    report: dict[str, Any] = {
        'schema_version': 1,
        'run_dir': str(run_dir),
        'formats': formats,
        'live_model': {
            'status': 'not_run',
            'reason': 'This command calls deterministic local toolsets '
            'and contacts no model provider.',
        },
        'limitations': [
            'Synthetic fixtures cover representative cases, not every possible input.',
            'Automated pass does not establish visual quality or calculated workbook results.',
            'Native-render and visual-review statuses require independent review '
            'of these exact hashes.',
            *document_limitations,
        ],
    }
    errors = validate_report(report)
    report['automated'] = {'status': 'fail' if errors else 'pass', 'errors': errors}
    (run_dir / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main(argv: list[str] | None = None) -> int:
    """Write an aggregate report and return nonzero if any automated gate fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    report = run(output_dir)
    errors = validate_report(report)
    report['automated'] = {'status': 'fail' if errors else 'pass', 'errors': errors}
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / 'report.json'
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Automated checks: {report["automated"]["status"]}. Report: {target}')
    print('Native rendering and visual review: pending. Live model: not run.')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
