# AI providers

LLMs, multi-modal models, transcription, image generation, and search
APIs commonly used by agents.

## Agent-ready behavior (overview)

Across this group, only the **list / discovery** tools were touched for
agent ergonomics; chat / completion / embedding / image / TTS tools are
unchanged (they already return content, not lists). For each listing
tool you get:

- A compact summary array with a stable display ref
  (`model_ref`, `file_ref`, `batch_ref`, `job_ref`, `store_ref`,
  `voice_ref`, `prediction_ref`, `deployment_ref`,
  `transcript_ref`, `project_ref`, `dataset_ref`, `kb_ref`) safe to
  show in final answers.
- Raw provider IDs are hidden by default. Pass `include_ids=True` only
  when a follow-up tool needs them.
- Default page size is 20-25 for resource lists (10 for AssemblyAI
  transcripts and Bedrock knowledge bases). Search APIs (Tavily, Brave,
  SerpAPI) cap `max_results` / `count` / `num` at 10.

Write tools that take an identifier (`get_file`, `delete_file`,
`create_batch`, `get_batch`, `cancel_batch`, `delete_response`,
`get_vector_store`, `delete_vector_store`, `cancel_fine_tuning_job`,
`create_fine_tuning_job`, `get_prediction`, `cancel_prediction`,
`get_transcript`, `delete_transcript`, `lemur_task`) accept the dict
returned by the corresponding list / get tool as well as a raw ID
string.

For chat-style models, `list_models` always keeps the model name as
`model_name` because callers need it to invoke the model -- only
internal handles (file/batch/job/store/etc.) are hidden.

## OpenAIToolSet

```python
from maivn_tools import OpenAIToolSet

connector = OpenAIToolSet(api_key=secrets["OPENAI_API_KEY"])
```

Tools: `chat_completion`, `responses_create`, `get_response`,
`delete_response` (destructive), `create_embedding`, `list_models`,
`get_model`, `delete_fine_tuned_model` (destructive), `generate_image`,
`speech`, `list_files`, `get_file`, `delete_file` (destructive),
`create_batch`, `list_batches`, `get_batch`, `cancel_batch`
(destructive), `moderate`, `create_fine_tuning_job`,
`list_fine_tuning_jobs`, `cancel_fine_tuning_job` (destructive),
`create_vector_store`, `list_vector_stores`, `get_vector_store`,
`delete_vector_store` (destructive).

**Agent-ready behavior**

- `list_models` (default limit 20): summary with `model_ref`,
  `model_name`, `owned_by`, `created`. Set `include_ids=True` for raw
  `id`.
- `list_files` (default limit 20): summary with `file_ref`, `filename`,
  `purpose`, `bytes`, `created_at`, `status`. Raw `file-...` IDs
  hidden; opt in with `include_ids=True` (needed for `delete_file`,
  `create_batch`, `create_fine_tuning_job`).
- `list_batches` (default limit 20): summary with `batch_ref`,
  `endpoint`, `status`, `request_counts`, `created_at`. Opt in for raw
  `batch_id`.
- `list_fine_tuning_jobs` (default limit 20): summary with `job_ref`,
  `model`, `fine_tuned_model`, `status`, `created_at`. Opt in for raw
  `job_id`.
- `list_vector_stores` (default limit 20): summary with `store_ref`,
  `name`, `file_counts`, `status`, `created_at`. Opt in for raw
  `store_id`.
- Tolerant inputs: `get_file`, `delete_file`, `create_batch`,
  `get_batch`, `cancel_batch`, `get_vector_store`,
  `delete_vector_store`, `cancel_fine_tuning_job`, and
  `create_fine_tuning_job` accept the raw ID, the file/batch/job dict
  returned by the matching list tool, or the full `{"data": [...]}`
  list payload.
- Destructive: `delete_response`, `delete_fine_tuned_model`,
  `delete_file`, `cancel_batch`, `cancel_fine_tuning_job`,
  `delete_vector_store`. Confirm with the user before invoking.

```python
files = connector.list_files()                 # compact summaries
files = connector.list_files(include_ids=True) # also include file_id
connector.delete_file(files["files"][0])       # accepts the dict
```

## AnthropicToolSet

```python
from maivn_tools import AnthropicToolSet

connector = AnthropicToolSet(api_key=secrets["ANTHROPIC_API_KEY"])
```

Tools: `create_message`, `count_tokens`, `list_models`, `get_model`,
`create_message_batch`, `get_batch`, `cancel_batch` (destructive).

**Agent-ready behavior**

- `list_models` (default limit 20): summary with `model_ref`,
  `model_name`, `display_name`, `created_at`. `model_name` is kept
  because it is also the model identifier callers pass to
  `create_message`. Set `include_ids=True` to also include the raw
  `id`.
- `get_batch` and `cancel_batch` accept a raw `msgbatch_...` string or
  a batch dict returned by `create_message_batch` / `get_batch`.
- Destructive: `cancel_batch`. Confirm before invoking.

```python
models = connector.list_models()
batch = connector.create_message_batch(requests=[...])
connector.get_batch(batch)  # dict accepted
```

## AzureOpenAIToolSet

```python
from maivn_tools import AzureOpenAIToolSet

connector = AzureOpenAIToolSet(
    endpoint="https://my-rsrc.openai.azure.com",
    api_key=secrets["AZURE_OPENAI_KEY"],
    api_version="2024-08-01-preview",
)
```

Tools: `chat_completion(deployment, ...)`, `embeddings(deployment, ...)`,
`generate_image(deployment, ...)`, `list_models`.

**Agent-ready behavior**

- `list_models` (default limit 25): summary with `model_ref`,
  `model_name`, `capabilities`, `lifecycle_status`. `model_name` is
  kept because it is the deployment identifier callers pass to
  `chat_completion` / `embeddings` / `generate_image`. Set
  `include_ids=True` for the raw `id`.

## GeminiToolSet

Google AI Studio / Generative Language API.

```python
from maivn_tools import GeminiToolSet

connector = GeminiToolSet(api_key=secrets["GEMINI_API_KEY"])
```

Tools: `generate_content`, `count_tokens`, `embed_content`,
`list_models`, `get_model`.

**Agent-ready behavior**

- `list_models` (default limit 25): summary with `model_ref`,
  `model_name`, `display_name`, `supported_methods`,
  `input_token_limit`, `output_token_limit`. `model_name` is the
  `"models/..."` resource name callers pass to `generate_content`. Set
  `include_ids=True` for the raw `name`.

## BedrockToolSet

AWS Bedrock Runtime + control plane. Pass a SigV4 `AuthStrategy`.

```python
from maivn_tools import BedrockToolSet

connector = BedrockToolSet(region="us-east-1", auth=sigv4_auth)
```

Tools: `list_foundation_models`, `converse`, `invoke_model`,
`list_knowledge_bases`, `retrieve`.

**Agent-ready behavior**

- `list_foundation_models` (default limit 25): summary with
  `model_ref`, `model_name`, `provider`, `input_modalities`,
  `output_modalities`, `model_lifecycle`. `model_name` is the
  `modelId` callers pass to `converse` / `invoke_model`. Set
  `include_ids=True` for the raw `model_arn`.
- `list_knowledge_bases` (default limit 10): summary with `kb_ref`,
  `knowledge_base_id` (kept because callers need it for `retrieve`),
  `name`, `description`, `status`, `updated_at`. Set
  `include_ids=True` for the raw `knowledge_base_arn`.

## MistralToolSet

```python
from maivn_tools import MistralToolSet

connector = MistralToolSet(api_key=secrets["MISTRAL_API_KEY"])
```

Tools: `chat_completion`, `embeddings`, `fim_completion`, `list_models`.

**Agent-ready behavior**

- `list_models` (default limit 25): summary with `model_ref`,
  `model_name`, `owned_by`, `created`. `model_name` is kept because it
  is also the identifier callers pass to `chat_completion`. Set
  `include_ids=True` for the raw `id`.

## CohereToolSet

```python
from maivn_tools import CohereToolSet

connector = CohereToolSet(api_key=secrets["COHERE_API_KEY"])
```

Tools: `chat`, `embed`, `rerank`, `list_models`.

**Agent-ready behavior**

- `list_models` (default limit 20): summary with `model_ref`,
  `model_name`, `endpoints`, `context_length`. `model_name` is the
  identifier callers pass to `chat` / `embed`. Set `include_ids=True`
  for the raw `name`.

## HuggingFaceToolSet

```python
from maivn_tools import HuggingFaceToolSet

connector = HuggingFaceToolSet(token=secrets["HF_TOKEN"])
```

Tools: `list_models`, `get_model`, `list_datasets`, `run_inference`,
`whoami`.

**Agent-ready behavior**

- `list_models` (default limit 25): summary with `model_ref`,
  `model_name` (the `"author/name"` string callers pass to
  `run_inference`), `pipeline_tag`, `downloads`, `likes`,
  `last_modified`. Set `include_ids=True` for the raw `id`.
- `list_datasets` (default limit 25): summary with `dataset_ref`,
  `dataset_name`, `tags`, `downloads`, `last_modified`. Set
  `include_ids=True` for the raw `id`.

```python
hits = connector.list_models(search="bert", max_results=10)
```

## ReplicateToolSet

```python
from maivn_tools import ReplicateToolSet

connector = ReplicateToolSet(api_token=secrets["REPLICATE_TOKEN"])
```

Tools: `list_models`, `get_model`, `create_prediction`,
`get_prediction`, `cancel_prediction` (destructive), `list_predictions`,
`list_deployments`, `predict_deployment`.

**Agent-ready behavior**

- `list_models` (default limit 25): summary with `model_ref`,
  `model_name` (`"owner/name"`), `owner`, `name`, `description`,
  `run_count`, `visibility`. Set `include_ids=True` to surface
  `latest_version_id` (needed for pinned-version `create_prediction`).
- `list_predictions` (default limit 25): summary with `prediction_ref`,
  `version`, `status`, `created_at`, `completed_at`. Raw prediction
  IDs hidden; opt in with `include_ids=True` (needed for
  `get_prediction` / `cancel_prediction`).
- `list_deployments` (default limit 25): summary with `deployment_ref`,
  `owner`, `name`, `deployment_path`, `current_release_version`. Opt
  in for the raw `id`.
- Tolerant inputs: `get_prediction` and `cancel_prediction` accept a
  raw prediction ID, a prediction dict returned by
  `create_prediction` / `list_predictions`, or the
  `{"results": [...]}` list payload.
- Destructive: `cancel_prediction`. Confirm before invoking.

## StabilityToolSet

```python
from maivn_tools import StabilityToolSet

connector = StabilityToolSet(api_key=secrets["STABILITY_KEY"])
```

Tools: `get_account`, `get_balance`, `generate_image`, `upscale`,
`edit_inpaint`.

**Agent-ready behavior**

- No list tools; the only read tools (`get_account`, `get_balance`)
  return small scalar responses already useful as-is.

## ElevenLabsToolSet

```python
from maivn_tools import ElevenLabsToolSet

connector = ElevenLabsToolSet(api_key=secrets["ELEVENLABS_KEY"])
```

Tools: `text_to_speech`, `speech_to_text`, `list_voices`, `get_voice`,
`list_models`, `get_user`.

**Agent-ready behavior**

- `list_voices` (default limit 25): summary with `voice_ref`, `name`,
  `voice_id` (kept because callers need it for `text_to_speech` /
  `get_voice`), `category`, `labels`, `description`. Set
  `include_ids=True` for a redundant `id` field.
- `list_models` (default limit 25): summary with `model_ref`,
  `model_name`, `name`, `languages`, `can_do_text_to_speech`,
  `can_use_style`. Set `include_ids=True` for the raw `model_id`.

## DeepgramToolSet

```python
from maivn_tools import DeepgramToolSet

connector = DeepgramToolSet(api_key=secrets["DEEPGRAM_KEY"])
```

Tools: `transcribe_url`, `transcribe_bytes`, `speak`, `list_projects`.

**Agent-ready behavior**

- `list_projects` (default limit 25): summary with `project_ref`,
  `name`, `company`. Raw `project_id` is hidden by default; opt in
  with `include_ids=True` when a follow-up Deepgram tool needs the raw
  ID.

## AssemblyAIToolSet

```python
from maivn_tools import AssemblyAIToolSet

connector = AssemblyAIToolSet(api_key=secrets["ASSEMBLYAI_KEY"])
```

Tools: `upload`, `submit_transcript`, `get_transcript`,
`list_transcripts`, `delete_transcript` (destructive), `lemur_task`.

**Agent-ready behavior**

- `list_transcripts` (default limit 10): summary with
  `transcript_ref`, `status`, `audio_url`, `created`, `completed`. Raw
  transcript IDs hidden; opt in with `include_ids=True` (needed for
  `get_transcript`, `delete_transcript`, `lemur_task`).
- Tolerant inputs: `get_transcript`, `delete_transcript`, and
  `lemur_task` accept a raw transcript ID, a transcript dict, or the
  `{"transcripts": [...]}` list payload. `lemur_task` accepts a list
  of any of the above.
- Destructive: `delete_transcript`. Confirm before invoking.

```python
recent = connector.list_transcripts(include_ids=True)
connector.delete_transcript(recent["transcripts"][0])
```

## TavilyToolSet

```python
from maivn_tools import TavilyToolSet

connector = TavilyToolSet(api_key=secrets["TAVILY_KEY"])
```

Tools: `search`, `extract`, `crawl`.

**Agent-ready behavior**

- `search` is a search API, not a list tool: it returns the raw Tavily
  response (`results[*]` with `title`, `url`, `content`) which is
  already agent-friendly. `max_results` is capped at 10 (the actual
  cap is reported back on the response when the requested value
  exceeded the cap).

## BraveSearchToolSet / SerpAPIToolSet

Two web-search providers with similar surfaces:

```python
from maivn_tools import BraveSearchToolSet, SerpAPIToolSet

brave = BraveSearchToolSet(api_key=secrets["BRAVE_KEY"])
serp  = SerpAPIToolSet(api_key=secrets["SERPAPI_KEY"])
```

Each exposes `web_search`. Brave also has `news_search`,
`image_search`, `video_search` and adds `suggest`. SerpAPI adds
`location_search` and `get_account`.

> The Bing Web Search API was retired by Microsoft on 2025-08-11 and is
> no longer available; the connector was removed. Use Brave/SerpAPI, or
> Grounding with Bing Search in the Azure AI Agents Service.

**Agent-ready behavior**

- All search tools return raw provider responses (Brave
  `web.results[*]`, SerpAPI `organic_results[*]`) -- the per-hit fields
  (`title`/`name`, `url`/`link`, `snippet`/`description`/`content`) are
  already human-readable, so they are kept.
- `count` (Brave) and `num` (SerpAPI) cap results to keep agent runs
  fast; values above each provider's max are clamped.
