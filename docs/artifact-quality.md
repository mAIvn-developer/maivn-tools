# Artifact quality benchmark

Run representative creation and revision workflows through the public document,
PDF, presentation and workbook toolsets. The benchmark is local and deterministic:
it does not call a model, start services or contact a paid provider.

From `libraries/maivn-tools`, with the component's development dependencies available:

```powershell
uv run python -m evals.artifact_quality --output-dir ../../.maivn-logs/agents/artifact-quality/benchmark
```

`--output-dir` is required. Use an ignored output directory. Each execution retains
its artifacts and report under a fresh `run-*` directory, so rerunning the command
does not overwrite previous artifacts. The command also writes the latest aggregate
report to `<output-dir>/report.json`.

Exit code `0` means every automated gate passed and all eight artifact files match
their recorded SHA-256 hashes. A failed evaluator, missing format, empty checks,
non-boolean or false check, missing file, or hash mismatch produces a nonzero exit.
Independent format evaluators continue after another format fails.

## What the fixtures cover

| Format | Initial artifact | Revision and checks |
| --- | --- | --- |
| DOCX | Proposal with headings, Western European Unicode and 28 table records | Budget edit, content preservation, table completeness, repeated headers and unchanged style/table structure |
| PDF | The same proposal across multiple pages | Budget edit, Unicode extraction, repeated table headers, record completeness and stable page count |
| PPTX | Five-slide operating review with native metrics chart, responsibilities table and recommendation | Four-week recommendation changes to six weeks; chart/table content, slide geometry and unrelated compositions remain intact |
| XLSX | Assumptions, forecast and summary sheets with editable inputs, 27 formulas and a linked chart | Starting volume changes from 100 to 120; exact formula map, formatting, freeze panes and chart references remain intact |

The fixture data is illustrative. A structural check is evidence for the property
it names. It is not a universal quality score.

## Read the result in separate stages

The report separates `automated`, `native_render`, `visual_review`, `calculation`
and `live_model` evidence. Automated checks can pass while the other stages remain
pending. The deterministic runner always leaves native rendering and visual review
pending, workbook calculation pending (or `not_run` if its evaluator failed), and
live-model execution `not_run`.

To complete a quality review:

1. Open the exact generated DOCX, PPTX and XLSX files in Word, PowerPoint and Excel,
   or another independent compatible engine. Record application/version and whether
   any repair prompt appears. Export every page, slide and relevant sheet to PDF or
   page images. Render generated PDFs with an independent PDF renderer.
2. Inspect every rendered page or slide at a readable size. Check missing text,
   glyphs, clipping, overlaps, table wrapping and continuation, chart labels, legends,
   units and print scale. Compare the original and revision, including unchanged
   content. Font substitution and pagination can differ between applications.
3. Recalculate the XLSX in Excel or another calculation engine. Compare cached
   results with `calculation_expectations` in the workbook evidence. Reading formula
   strings with `openpyxl` does not calculate them. A formula source can be preserved
   while its result is wrong.
4. Keep review evidence beside the run, binding it to the exact initial and revised
   SHA-256 hashes from `artifacts`. Include preview paths, observations and limitations.
   An edited or newly generated file needs a fresh review. The runner does not import
   or automatically approve external review notes.

Live-model evaluation is a separate workflow. If one is performed, use an
application-owned driver and an explicitly approved provider budget. Record the
actual model selection, prompt or fixture identity, tool calls, generated artifact
hashes, revision outcome, and failures. Preserve the deterministic benchmark's
independent native-rendering and workbook-recalculation checks. A toolset benchmark
does not establish that every model can plan or complete the same workflow.

## Current limits and controls

- **Fonts:** DOCX uses Arial. PDF embeds ReportLab's Vera fonts, supports their glyph
  coverage and rejects unsupported glyphs. PPTX defaults use Aptos/Aptos Display;
  the benchmark explicitly requests Arial. Presentation `font_family`, `font_size`
  and text/table alignment can be specified per element; chart font settings apply
  to axes and legends. XLSX uses Aptos. Office fonts are not embedded by these tools.
- **Presentation layout:** `inspect_layout` estimates text/table capacity and reports
  intersecting element bounds. It cannot prove text fit or detect every chart-label
  problem. Charts remain editable clustered columns. Large tables and long labels
  need deliberate placement and rendered inspection.
- **Workbook formulas:** Use `kind='formulas'` for calculations. Supported syntax is
  internal A1 cells/ranges, quoted or unquoted sheet references, `$` absolute references,
  numbers, `+ - * / ^`, parentheses, percentages, and `SUM`, `AVERAGE`, `MIN`, `MAX`,
  `COUNT`. For example, `=Assumptions!$B$2*(1+15%)`. External workbook references,
  other functions and named ranges are unsupported. Syntax and coordinate validation
  do not calculate results or prove that a referenced sheet exists. Strings supplied
  as ordinary scalar/row/matrix data remain literal, even when they begin with `=`.
- **Workbook charts:** `format.chart.source_range` can name a rectangle on the same
  sheet, such as `A9:C12`. Its first row supplies headers, the first column supplies
  categories, and subsequent columns supply numeric series. This allows charting formula
  cells placed in separately formatted ranges. Omit it to use the attached range.
  The rectangle must include at least two rows and two columns. Cross-sheet chart
  sources and automatic detection of a suitable data range are unsupported.
- **Workbook edits:** Use separate non-overlapping rectangles for different formats
  and for literal data versus formulas. A vertical column uses matrix rows such as
  `[["January"], ["February"]]`. Set unused content fields to null or omit them.
  Reusing a composition ID updates its placements and refreshes their occupied cells.
  Resizing into another range is rejected before saving. Read the workbook and reuse
  existing range IDs when correcting placements. Structured validation reports the
  failed rule without echoing cell contents.
- **Image edits:** Owned provider clients close within each generation or edit call,
  including stream completion, errors and cancellation. This supports repeated sync
  SDK invocations that use separate event loops. A supplied client remains owned by
  its caller. Narrow image edits can still change texture or lighting outside the
  requested area; compare every result visually when exact preservation matters.
- **Tables and printing:** PDF records taller than a page need to be split before
  rendering. Workbook wrapping and print sizing use estimates; wide sheets may need
  landscape orientation or actual-size printing. Inspect the rendered output.

## Extend the benchmark

Add a format-specific fixture using its public toolset API, explicit content checks,
and paired original/revised artifacts. Extend the runner's format expectations and
tests deliberately. Keep native rendering, calculation and visual checks appropriate
to that format. New file support does not imply that one generic validator can assess
its quality, and it does not require a universal aesthetic score.

Focused regression checks:

```powershell
uv run pytest tests/evals/test_artifact_quality.py -q
```

These tests execute the real evaluators and reject missing/false gates, changed file
bytes and a workbook renderer mutation that deletes every formula.
