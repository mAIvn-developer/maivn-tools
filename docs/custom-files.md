# Files from custom toolsets

A developer toolset can return any nonempty file up to 50 MiB using
`maivn.files.generated_file`. CSV, ZIP, and future extensions use
`kind="other"` and `application/octet-stream`: authenticated attachment download,
with the original extension preserved. Adding another such format requires no
SDK, Data Plane, Vault, or Studio format-specific code. This generic route does
not promise inline previews, content validation, or an editor for that format.
Known DOCX, PDF, XLSX, PPTX, PNG, and JPEG files retain their specialized identities
and checks. An unsupported `mime_type` argument also selects the generic route.

```python
from pathlib import Path

from maivn import Agent, Client, toolify, toolset
from maivn.files import GeneratedFile, generated_file


@toolset(prefix="exports", metadata={"serialize_calls": True})
class ExportTools:
    def __init__(self, output_dir: Path, *, private: bool = False):
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.private = private

    def authorized_generated_file_roots(self) -> tuple[Path, ...]:
        return (self.output_dir,)

    @toolify()
    def export(self) -> GeneratedFile:
        path = self.output_dir / "report.future-format"
        path.write_bytes(b"Format version 1\nSynthetic example\n")
        return generated_file(
            path,
            custody="vault_private" if self.private else "ordinary",
        )


# Private outputs go to the same API address as every other call.
client = Client(api_key=api_key)
agent = Agent(name="Custom exports", client=client)
agent.add_toolset(ExportTools(Path("outputs"), private=True))
```

The `GeneratedFile` return annotation declares automatic intake. Actual
`GeneratedFile` and `GeneratedFiles` objects also enter custody intake when a
return annotation is omitted; missing authorization fails without publishing
local file metadata. For an ordered batch, annotate `GeneratedFiles` and return
its bounded `files` tuple. Existing
`@tool_output(GeneratedFile)` declarations also work. Register the actual bound
toolset instance; dictionaries that merely resemble file contracts do not grant
filesystem access.

Choose the output directory in application configuration. The
`authorized_generated_file_roots` hook grants the SDK permission to read files
only beneath those roots. Do not expose an unrestricted path or root argument to
the model. The helper captures immutable bytes beneath
`output_dir/.maivn-generated/<capture-id>/`, preserving the filename. Subsequent
writes to the original path cannot change a pending upload. The application owns
cleanup of successful local captures; a failed helper removes its own incomplete
capture and preserves the input file.

## Optional editable source

For a custom editor, supply its source bytes and a versioned adapter identifier:

```python
output = generated_file(
    path,
    custody="vault_private",
    source=source_bytes,
    source_format="example.export/v1",
)
```

The SDK retains those bytes outside the model-facing `GeneratedFile` JSON,
associates them with the exact tool call and output slot, and admits them with the
output. Existing toolsets may instead implement
`export_generated_file_source(generated)` to return their own
`maivn-source-archive-v1` package. The helper source takes precedence when supplied.

Custom helper packages use `workspace_type="binary"`. Their manifest contains
`editable=true`, `filename`, `source_format`, and base64-encoded `content_base64`.
Without source bytes, the manifest contains `editable=false` and `filename`; it
does not duplicate the original file. The enclosing `output_sha256` binds the
source to exact output bytes. `editable_source_archive(output, source=None,
source_format=None)` is also available for application-owned source hooks.

For ordinary outputs, call `client.artifacts.download_source(ref,
session_id=session_id)`. For private outputs, call
`client.private_artifacts.download_source(ref, session_id=session_id)`. Private
filenames and custom source bytes remain inside the encrypted Vault source
package. Original private downloads use `download_to(ref, local_path,
session_id=session_id)`, where the application chooses the destination name.
The custom application validates its adapter version and reconstructs its local
editable state; the platform never imports or executes an unknown format adapter.

Pass the exact downloaded output reference to the next `generated_file` call as
`expected_base=ordinary_ref` or `private_expected_base=private_ref`. The server
enforces the same owner, thread, logical output, and expected-base revision rules
as built-in toolsets. A filename alone never authorizes a revision. Keep an
unchanged old reference when downloading old revisions.

A custom toolset remains responsible for safe model-facing readback and error
messages. Putting a file in private custody does not make arbitrary application
code that returns its plaintext safe. Built-in artifact toolsets provide
workspace-scoped opaque readback selectors; custom source adapters should expose
only the values and operations their application authorizes.
