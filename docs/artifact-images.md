# Images in editable artifacts

`DocumentsToolSet`, `PDFToolSet`, and `PresentationsToolSet` support PNG and JPEG
images through their persisted, stepwise composition APIs. Each image is fitted
inside an explicit box without cropping or stretching. Other compositions remain
intact when a text composition is updated, including after a new toolset instance
reopens the same output directory and handle.

## Model-directed artifact image composition

When these toolsets run through the SDK, `compose_artifact_image` accepts a
`doc` handle, `composition_id`, exact `artifact_id`, and `alt_text`. The image ID
must come from a caller message attachment or a completed generated-image
outcome in the same invocation. It accepts no model-controlled URL, local path,
or base64 payload. Place the returned composition with `put_block` (DOCX/PDF)
or `put_element` (PPTX), as shown below.

The SDK independently authorizes the exact ordinary or Vault reference before
downloading its bytes. Invented IDs and conflicting references fail closed.
Private image composition persists private source custody; subsequent renders
and portable source packages use Vault intake even without a private message
map. Tool readback uses opaque private image IDs instead of content hashes.

This bridge consumes generated or attached images; it does not itself call an
image generation provider. The caller-local `compose_image` API remains useful
when an application already holds authorized image bytes.

## SDK-host image generation and editing

`ImagesToolSet` runs the configured image provider on the application host. Add
it to an SDK `Agent` alongside the document toolsets; Studio is optional. Its
constructor defaults to `custody='vault_private'`. The SDK publishes generated
files and encrypted editable sources through Vault, then returns canonical
private references. Set `custody='ordinary'` explicitly for ordinary outputs.

The core `maivn-tools` package accepts an application implementation of
`maivn_tools.connectors.images.ImageGenerator`; it does not install Brain or
provider clients. An implementation receives the canonical image intent and
local reference bytes and returns `ImageProviderBatch`. Applications that
already use Brain can install `maivn-brain` separately and reuse its routing:

```python
from maivn import Agent, Client, SystemToolsConfig
from maivn_tools import DocumentsToolSet, ImagesToolSet, RoutedImageGenerator

# Application configuration: a trusted Brain catalog snapshot and configured
# provider adapters keyed by catalog key. Credentials stay in those adapters.
generator = RoutedImageGenerator(
    catalog=trusted_catalog_snapshot,
    providers=configured_image_providers,
)
images = ImagesToolSet(output_dir / 'images', generator=generator)
client = Client(api_key=maivn_api_key)
agent = Agent(
    name='Illustrated reports',
    client=client,
    system_prompt='Generate illustrations, compose the report, and render it.',
    system_tools_config=SystemToolsConfig(allowed_tools=[]),
)
agent.add_toolset(images)
agent.add_toolset(DocumentsToolSet(output_dir / 'documents'))
```

`generate_images` accepts a prompt, pixel dimensions, one to four outputs, and
standard or high quality. `edit_image` accepts an exact attached or newly
generated image ID and an edit prompt. The SDK authorizes and downloads the
selected immutable input; the output carries that reference as its expected
base. A private base remains private even on a toolset configured for ordinary
outputs. A toolset configured for private outputs refuses an ordinary revision
instead of silently changing its custody. Register a separate ordinary toolset
when ordinary revisions are needed.

Provider work has a 300-second deadline by default. Applications can set a
positive finite `provider_timeout_seconds` in the constructor; this setting is
not exposed as a model argument. A deadline cancels local work and fails without
publishing a partial result.

The model can pass returned image IDs to `compose_artifact_image` on DOCX, PDF,
or PPTX toolsets. Private images make the enclosing artifact private before
rendering or source export. Images and outputs are bounded and normalized;
provider error details, inline bytes, and local paths do not appear in private
tool outcomes. Provider routing and credentials are application configuration,
not model arguments. The Brain adapter retains the existing router's retryable
fallback and terminal safety-refusal behavior.

To continue on a fresh host, retrieve the exact authorized source and restore
an image handle, then call `edit_source` through the registered toolset:

```python
source = client.private_artifacts.download_source(
    private_ref, session_id=current_session_id,
)
fresh_images = ImagesToolSet(new_output_dir, generator=generator)
handle = fresh_images.resume_private_artifact(private_ref, source=source)
# Supply this handle to the registered edit_source tool in the next invocation.
# A direct Python call returns a local GeneratedFile; automatic publication
# happens when the tool runs through the SDK Agent.
```

For ordinary images use `client.artifacts.download_source` and
`resume_artifact` on an ordinary toolset. Source packages preserve the image,
generation intent, and edit inputs. Private packages are encrypted in Vault;
the local output directory remains application-owned private storage. Sensitive
prompt values must use the SDK's private placeholder resolution: ordinary
messages and tool argument strings still travel through the data plane.

These APIs require the matching server source/revision and Vault intake
configuration and migrations. They do not enable hosted private image
generation in the data plane. This implementation has deterministic provider,
real Brain routing/fallback, source restoration, and private intake contract
tests. Live ordinary SDK verification generated an image with `openai/gpt-image-2`,
restored its server-held source on a fresh host, and edited it through configured
provider fallback. Both immutable image revisions remained downloadable. The
revised image was also composed into a downloaded DOCX and visually checked;
local DOCX and PPTX composition passed visual review. These checks do not establish
end-to-end Vault publication. Current tool methods expose generation and
single-image editing, not mask editing or multiple reference inputs.

## Caller-local image admission

The application first resolves the exact authorized image artifact through its
normal transport. It then calls `compose_image` locally. This method is deliberately
not registered as a model tool. Base64 bytes, filesystem paths, and download URLs
are absent from image composition references and read-back responses.

```python
import base64
from maivn_tools import DocumentsToolSet

documents = DocumentsToolSet(output_dir)
handle = documents.create_document('report.docx')
image_ref = documents.compose_image(
    handle,
    'overview-image',
    content_base64=base64.b64encode(authorized_png_bytes).decode('ascii'),
    mime_type='image/png',
    alt_text='Three bars showing increasing readiness',
)
documents.put_block(
    handle,
    'overview-image',
    {
        'type': 'image',
        'composition': image_ref,
        'image_placement': {
            'width_inches': 5.5,
            'height_inches': 3.0,
            'alignment': 'center',
        },
    },
    {'anchor': 'end'},
)
generated = documents.render_document(handle)
```

PDF uses the same placement shape. DOCX boxes must fit within 6 by 8.5 inches;
PDF boxes within 6.3 by 9.2 inches. Alignment is `left`, `center`, or `right`.
The actual image can be smaller than the specified box to retain its aspect ratio.

For presentations, use `compose_image` on a presentation handle, then place an
`image` element with the existing `x`, `y`, `width`, and `height` inch coordinates.
The image is centered inside that box, which must stay within the 13.333 by 7.5
inch canvas. Image composition uses the stepwise API, not the one-shot helpers.

Admission checks the declared MIME against decoded bytes, rejects animation,
limits encoded input and normalized output to 8 MiB, and permits at most 16 million
pixels with either dimension at most 8192 pixels. It applies EXIF orientation and
re-encodes the pixels without source metadata. Alternative text is required and
limited to 1000 characters; DOCX and PPTX store it in the picture description.
PDF images are visual flowables and do not add tagged-PDF accessibility metadata.

The source manifest stores normalized assets by digest. Read-back exposes only
`asset_id` and `alt_text`; a model can reuse that reference in `compose_artifact`
within the same workspace. Unknown asset references and changed asset bytes are
rejected. `GeneratedFile` remains the existing strict output contract.

## Presentation typography and layout checks

Title, text, and list elements accept `font_size` (6–96 points), `font_family`
(up to 100 characters), and `alignment` (`left`, `center`, or `right`). Text wraps
within the existing box. Font availability depends on the viewing application.

`inspect_layout(presentation)` returns issues with `slide_id`, `element_id`,
`code`, and a repair suggestion. It flags likely `text_overflow` and intersecting
element bounds as `element_overlap`. These are estimates: font metrics, complex
scripts, tables, and intentional layering require a final visual check in an
Office renderer. Inspection does not silently modify authored content.

## Workbook print layout

Workbook sheets also accept typed `print_settings` in `put_sheet` and one-shot
sheet inputs: `mode` is `auto`, `fit_width`, or `actual_size`; optional
`orientation` is `portrait` or `landscape`; `minimum_scale_percent` is 50–100
(default 70). By default, compact sheets including chart bounds fit one page
wide with unlimited vertical pages. Sheets estimated to need smaller text keep
100% scale and horizontal pagination. An explicit `fit_width` request fails if
it cannot meet the minimum scale; choose landscape or `actual_size`. Settings
survive subsequent sheet edits that omit `print_settings`. Width estimates use
Excel character widths, so final print inspection remains necessary.

## Persistence and custody limits

The document, PDF, presentation, and workbook toolsets declare
`metadata={'serialize_calls': True}`. The SDK applies calls to each toolset
instance in order, including reads and rendering. Parallel model calls that
append blocks therefore preserve the requested order. Separate toolset
instances can still run concurrently. Custom stateful toolsets can use the
same metadata on `@toolset`; this ordering is local to one SDK invocation.

Procedural functions such as `put_block` remain available after a successful
call, so the model can place several distinct blocks in one invocation. A new
call ID denotes a new operation; replaying an identical start event within the
same SDK stream does not execute it twice. Conflicting reuse of a call ID fails.
Explicit dependency and constructor workflows retain their completion rules,
and invocation iteration limits still bound model-directed work. Stream replay
protection does not provide durable execution deduplication after process loss.

Reopen a persisted handle by constructing a new toolset with the same output
directory. Each render also freezes its output bytes and editable source. The
returned `GeneratedFile.path` names that immutable snapshot, so another render
of the same filename cannot replace bytes waiting for upload.

When registered with the SDK, these toolsets export a bounded
`maivn-source-archive-v1` package containing the exact composition and embedded
assets. Ordinary intake stores it alongside the exact artifact revision; private
intake stores it encrypted in Vault. Source retention and deletion follow the
artifact. A newly constructed toolset on another host can resume an authorized
source without the original output directory:

```python
source = client.artifacts.download_source(ref, session_id=current_session_id)
handle = fresh_documents.resume_artifact(ref, source=source)

private_source = client.private_artifacts.download_source(
    private_ref, session_id=current_session_id,
)
private_handle = fresh_documents.resume_private_artifact(
    private_ref, source=private_source,
)
```

Use the matching document, PDF, presentation, or workbook toolset. Editing and
rendering a resumed handle carries the selected exact reference as the expected
base. The server checks tenant, authenticated owner, conversation, and latest
revision before admitting the next immutable revision. A stale base fails;
previous revisions keep their original downloadable bytes. A filename never
selects revision authority. These APIs restore composition packages, not arbitrary
existing Office files.

The local workspace remains caller-owned storage. Local locks preserve call
ordering within one owning process; server admission supplies authorization and
revision conflict checks. Explicit `GeneratedFile(custody='vault_private', ...)`,
a private expected base, or private invocation data selects Vault publication.
Private sources require the authorized SDK/Vault path and never fall back to
ordinary intake. The source transport and revision database migrations must be
installed on the server before deploying clients that publish editable sources.


Private source readback through registered SDK toolsets returns opaque placeholders
for source text, filenames, custom selectors, table values, and spreadsheet cells.
The model can pass these placeholders back to the same workspace during the
invocation; the SDK restores their original values locally. The mapping stays in
the SDK process and cannot be reused across workspaces or later invocations.
Fresh private source restoration returns a handle with an opaque filename, so
applications can give that handle to the next agent without exposing the original
filename. Rendering retains the original filename inside private custody. This
also applies to restored image handles; image generation prompts remain in the
private source package and are not exposed by an image readback tool.
