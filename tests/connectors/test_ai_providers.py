# pyright: strict
from __future__ import annotations

import pytest

from maivn_tools.connectors.anthropic import AnthropicToolSet
from maivn_tools.connectors.assemblyai import AssemblyAIToolSet
from maivn_tools.connectors.azure_openai import AzureOpenAIToolSet
from maivn_tools.connectors.bedrock import BedrockToolSet
from maivn_tools.connectors.brave_search import BraveSearchToolSet
from maivn_tools.connectors.cohere import CohereToolSet
from maivn_tools.connectors.deepgram import DeepgramToolSet
from maivn_tools.connectors.elevenlabs import ElevenLabsToolSet
from maivn_tools.connectors.gemini import GeminiToolSet
from maivn_tools.connectors.huggingface import HuggingFaceToolSet
from maivn_tools.connectors.mistral import MistralToolSet
from maivn_tools.connectors.replicate import ReplicateToolSet
from maivn_tools.connectors.serpapi import SerpAPIToolSet
from maivn_tools.connectors.stability import StabilityToolSet
from maivn_tools.connectors.tavily import TavilyToolSet
from maivn_tools.testing import MockTransport, json_response, text_response


def test_anthropic() -> None:
    transport = MockTransport()
    connector = AnthropicToolSet(api_key="sk-ant", transport=transport)
    for _ in range(7):
        transport.enqueue(json_response({}))
    connector.create_message(
        model="claude-3-5-sonnet-latest",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        system="be brief",
        temperature=0.5,
        tools=[{"name": "x"}],
        tool_choice={"type": "any"},
        stop_sequences=["END"],
        metadata={"user_id": "u"},
        stream=False,
    )
    connector.count_tokens(
        model="claude-3-5-sonnet-latest",
        messages=[{"role": "user", "content": "hi"}],
        system="x",
        tools=[{"name": "y"}],
    )
    connector.list_models()
    connector.get_model("claude-3-5-sonnet-latest")
    connector.create_message_batch([{"custom_id": "c1", "params": {}}])
    connector.get_batch("b1")
    connector.cancel_batch("b1")
    assert transport.requests[0].headers["x-api-key"] == "sk-ant"
    assert transport.requests[0].headers["anthropic-version"] == "2023-06-01"
    with pytest.raises(ValueError):
        AnthropicToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.create_message(model="", messages=[{"r": "u"}], max_tokens=1)
    with pytest.raises(ValueError):
        connector.create_message(model="m", messages=[], max_tokens=1)
    with pytest.raises(ValueError):
        connector.create_message(model="m", messages=[{"r": "u"}], max_tokens=0)
    with pytest.raises(ValueError):
        connector.count_tokens(model="", messages=[{}])
    with pytest.raises(ValueError):
        connector.get_model("")
    with pytest.raises(ValueError):
        connector.create_message_batch([])
    with pytest.raises(ValueError):
        connector.cancel_batch("")


def test_tavily() -> None:
    transport = MockTransport()
    connector = TavilyToolSet(api_key="tvly", transport=transport)
    for _ in range(3):
        transport.enqueue(json_response({}))
    connector.search(
        "ai",
        search_depth="advanced",
        max_results=10,
        include_answer="basic",
        include_raw_content=True,
        include_images=True,
        include_domains=["a.com"],
        exclude_domains=["b.com"],
        days=7,
        time_range="day",
    )
    connector.extract(["https://x"], extract_depth="advanced", include_images=True)
    connector.crawl("https://x", max_depth=2, max_breadth=10, instructions="docs")
    assert transport.requests[0].headers["Authorization"] == "Bearer tvly"
    with pytest.raises(ValueError):
        TavilyToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.search("")
    with pytest.raises(ValueError):
        connector.search("x", search_depth="bogus")
    with pytest.raises(ValueError):
        connector.extract([])
    with pytest.raises(ValueError):
        connector.crawl("")


def test_brave_search() -> None:
    transport = MockTransport()
    connector = BraveSearchToolSet(api_key="b", transport=transport)
    for _ in range(5):
        transport.enqueue(json_response({}))
    connector.web_search("ai", country="us", search_lang="en", freshness="pw")
    connector.news_search("ai", freshness="pd")
    connector.image_search("ai")
    connector.video_search("ai")
    connector.suggest("ai")
    assert transport.requests[0].headers["X-Subscription-Token"] == "b"
    with pytest.raises(ValueError):
        BraveSearchToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.web_search("")


def test_serpapi() -> None:
    transport = MockTransport()
    connector = SerpAPIToolSet(api_key="sa", transport=transport)
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.search(
        "ai",
        engine="google",
        location="US",
        hl="en",
        gl="us",
        num=20,
        start=10,
    )
    connector.location_search("New York")
    connector.get_account()
    assert transport.requests[0].params["api_key"] == "sa"
    with pytest.raises(ValueError):
        SerpAPIToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.search("")
    with pytest.raises(ValueError):
        connector.location_search("")


def test_cohere() -> None:
    transport = MockTransport()
    connector = CohereToolSet(api_key="co", transport=transport)
    for _ in range(4):
        transport.enqueue(json_response({}))
    connector.chat(
        model="command-r-plus",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.5,
        max_tokens=100,
        tools=[{"name": "x"}],
        stream=False,
    )
    connector.embed(
        texts=["a"],
        model="embed-english-v3",
        input_type="classification",
        embedding_types=["float"],
    )
    connector.rerank(
        model="rerank-v3",
        query="ai",
        documents=["a", "b"],
        top_n=2,
    )
    connector.list_models()
    assert transport.requests[0].headers["Authorization"] == "Bearer co"
    with pytest.raises(ValueError):
        CohereToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.chat(model="", messages=[{}])
    with pytest.raises(ValueError):
        connector.embed(texts=[], model="m")
    with pytest.raises(ValueError):
        connector.rerank(model="m", query="", documents=[])


def test_mistral() -> None:
    transport = MockTransport()
    connector = MistralToolSet(api_key="m", transport=transport)
    for _ in range(4):
        transport.enqueue(json_response({}))
    connector.chat_completion(
        model="mistral-large-latest",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.5,
        max_tokens=100,
        tools=[{"name": "x"}],
        tool_choice="auto",
        response_format={"type": "json_object"},
        random_seed=42,
    )
    connector.embeddings(model="mistral-embed", input=["hi"])
    connector.fim_completion(
        model="codestral-latest",
        prompt="def hello():\n  ",
        suffix="\nprint(hello())",
        max_tokens=50,
        temperature=0.0,
    )
    connector.list_models()
    with pytest.raises(ValueError):
        MistralToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.chat_completion(model="", messages=[{}])
    with pytest.raises(ValueError):
        connector.embeddings(model="", input="x")
    with pytest.raises(ValueError):
        connector.fim_completion(model="", prompt="x", suffix="y")


def test_gemini() -> None:
    transport = MockTransport()
    connector = GeminiToolSet(api_key="g", transport=transport)
    for _ in range(5):
        transport.enqueue(json_response({}))
    connector.generate_content(
        model="models/gemini-1.5-pro",
        contents=[{"role": "user", "parts": [{"text": "hi"}]}],
        system_instruction={"parts": [{"text": "be brief"}]},
        tools=[{"functionDeclarations": []}],
        generation_config={"temperature": 0.5},
        safety_settings=[{"category": "HARM_X", "threshold": "BLOCK_NONE"}],
    )
    connector.count_tokens(
        model="models/gemini-1.5-pro",
        contents=[{"role": "user", "parts": [{"text": "hi"}]}],
    )
    connector.embed_content(
        model="models/text-embedding-004",
        content={"parts": [{"text": "hi"}]},
        task_type="SEMANTIC_SIMILARITY",
    )
    connector.list_models()
    connector.get_model("models/gemini-1.5-pro")
    assert transport.requests[0].headers["x-goog-api-key"] == "g"
    with pytest.raises(ValueError):
        GeminiToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.generate_content(model="", contents=[{}])
    with pytest.raises(ValueError):
        connector.count_tokens(model="x", contents=[])
    with pytest.raises(ValueError):
        connector.embed_content(model="m", content={})
    with pytest.raises(ValueError):
        connector.get_model("")


def test_bedrock() -> None:
    transport = MockTransport()
    connector = BedrockToolSet(region="us-east-1", transport=transport)
    for _ in range(5):
        transport.enqueue(json_response({}))
    connector.list_foundation_models(by_provider="anthropic", by_output_modality="TEXT")
    connector.converse(
        model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
        messages=[{"role": "user", "content": [{"text": "hi"}]}],
        system=[{"text": "be brief"}],
        inference_config={"maxTokens": 100},
        tool_config={"tools": []},
    )
    connector.invoke_model(model_id="amazon.titan-text-express-v1", body={"prompt": "hi"})
    connector.list_knowledge_bases()
    connector.retrieve(
        knowledge_base_id="kb1",
        query={"text": "ai"},
        number_of_results=10,
    )
    with pytest.raises(ValueError):
        BedrockToolSet(region="")
    with pytest.raises(ValueError):
        connector.converse(model_id="", messages=[{}])
    with pytest.raises(ValueError):
        connector.invoke_model(model_id="", body={})
    with pytest.raises(ValueError):
        connector.retrieve(knowledge_base_id="", query={"x": 1})


def test_huggingface() -> None:
    transport = MockTransport()
    connector = HuggingFaceToolSet(token="hf", transport=transport)
    for _ in range(4):
        transport.enqueue(json_response({}))
    transport.enqueue(text_response("output"))
    transport.enqueue(json_response({}))
    connector.list_models(search="bert", author="bert-base", filter="text", sort="trending")
    connector.get_model("bert-base-uncased")
    connector.list_datasets(search="squad", author="rajpurkar")
    connector.list_models()
    out = connector.run_inference(model="gpt2", payload={"inputs": "hi"})
    connector.whoami()
    assert out["body"] == "output"
    with pytest.raises(ValueError):
        HuggingFaceToolSet(token="")
    with pytest.raises(ValueError):
        connector.get_model("")
    with pytest.raises(ValueError):
        connector.run_inference(model="", payload={"x": 1})


def test_replicate() -> None:
    transport = MockTransport()
    connector = ReplicateToolSet(api_token="r8", transport=transport)
    for _ in range(7):
        transport.enqueue(json_response({}))
    connector.list_models()
    connector.get_model(owner="meta", name="llama-3")
    connector.create_prediction(version="abc", input={"prompt": "hi"})
    connector.create_prediction(
        model="meta/llama-3",
        input={"prompt": "hi"},
        webhook="https://x",
        stream=True,
    )
    connector.get_prediction("p1")
    connector.cancel_prediction("p1")
    connector.list_predictions()
    auth = transport.requests[0].headers["Authorization"]
    assert auth.startswith("Bearer ")
    with pytest.raises(ValueError):
        ReplicateToolSet(api_token="")
    with pytest.raises(ValueError):
        connector.get_model(owner="", name="x")
    with pytest.raises(ValueError):
        connector.create_prediction(input={})
    with pytest.raises(ValueError):
        connector.get_prediction("")
    with pytest.raises(ValueError):
        connector.cancel_prediction("")


def test_replicate_deployments() -> None:
    transport = MockTransport()
    connector = ReplicateToolSet(api_token="r8", transport=transport)
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.list_deployments()
    connector.predict_deployment(owner="me", name="d", input={"prompt": "hi"})
    with pytest.raises(ValueError):
        connector.predict_deployment(owner="", name="d", input={"x": 1})


def test_stability() -> None:
    transport = MockTransport()
    connector = StabilityToolSet(api_key="sk", transport=transport)
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(text_response("png"))
    transport.enqueue(text_response("png"))
    transport.enqueue(text_response("png"))
    connector.get_account()
    connector.get_balance()
    out = connector.generate_image(
        prompt="cat",
        model="ultra",
        aspect_ratio="16:9",
        negative_prompt="dog",
        seed=42,
    )
    assert out["body"] == b"png"
    connector.upscale(image_bytes=b"img", prompt="sharper")
    connector.edit_inpaint(image_bytes=b"img", mask_bytes=b"mask", prompt="add hat")
    with pytest.raises(ValueError):
        StabilityToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.generate_image(prompt="")
    with pytest.raises(ValueError):
        connector.generate_image(prompt="x", model="bogus")
    with pytest.raises(ValueError):
        connector.upscale(image_bytes=b"")
    with pytest.raises(ValueError):
        connector.edit_inpaint(image_bytes=b"", prompt="x")


def test_elevenlabs() -> None:
    transport = MockTransport()
    connector = ElevenLabsToolSet(api_key="x", transport=transport)
    transport.enqueue(text_response("mp3"))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    out = connector.text_to_speech(
        voice_id="v1",
        text="hello",
        voice_settings={"stability": 0.5},
    )
    assert out["body"] == b"mp3"
    connector.speech_to_text(audio_bytes=b"wav", diarize=True, language_code="en")
    connector.list_voices()
    connector.get_voice("v1")
    connector.list_models()
    connector.get_user()
    assert transport.requests[0].headers["xi-api-key"] == "x"
    with pytest.raises(ValueError):
        ElevenLabsToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.text_to_speech(voice_id="", text="x")
    with pytest.raises(ValueError):
        connector.speech_to_text(audio_bytes=b"")
    with pytest.raises(ValueError):
        connector.get_voice("")


def test_deepgram() -> None:
    transport = MockTransport()
    connector = DeepgramToolSet(api_key="dg", transport=transport)
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    transport.enqueue(text_response("mp3"))
    transport.enqueue(json_response({}))
    connector.transcribe_url(
        audio_url="https://x.wav",
        language="en",
        diarize=True,
        punctuate=False,
    )
    connector.transcribe_bytes(
        audio_bytes=b"audio",
        mime_type="audio/wav",
        language="en",
    )
    connector.speak(text="hello")
    connector.list_projects()
    auth = transport.requests[0].headers["Authorization"]
    assert auth.startswith("Token ")
    with pytest.raises(ValueError):
        DeepgramToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.transcribe_url(audio_url="")
    with pytest.raises(ValueError):
        connector.transcribe_bytes(audio_bytes=b"", mime_type="x")
    with pytest.raises(ValueError):
        connector.speak(text="")


def test_assemblyai() -> None:
    transport = MockTransport()
    connector = AssemblyAIToolSet(api_key="aai", transport=transport)
    for _ in range(7):
        transport.enqueue(json_response({}))
    connector.upload(audio_bytes=b"audio")
    connector.submit_transcript(
        audio_url="https://x.wav",
        speaker_labels=True,
        sentiment_analysis=True,
        entity_detection=True,
        summarization=True,
        iab_categories=True,
        language_code="en",
        webhook_url="https://h",
    )
    connector.get_transcript("t1")
    connector.list_transcripts()
    connector.delete_transcript("t1")
    connector.lemur_task(
        transcript_ids=["t1"],
        prompt="summarize",
        final_model="anthropic/claude-3-5-sonnet",
        max_output_size=2000,
        temperature=0.0,
    )
    assert transport.requests[0].headers["Authorization"] == "aai"
    with pytest.raises(ValueError):
        AssemblyAIToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.upload(audio_bytes=b"")
    with pytest.raises(ValueError):
        connector.submit_transcript(audio_url="")
    with pytest.raises(ValueError):
        connector.get_transcript("")
    with pytest.raises(ValueError):
        connector.delete_transcript("")
    with pytest.raises(ValueError):
        connector.lemur_task(transcript_ids=[], prompt="x")


def test_azure_openai() -> None:
    transport = MockTransport()
    connector = AzureOpenAIToolSet(
        endpoint="https://my-rsrc.openai.azure.com",
        api_key="k",
        api_version="2024-08-01-preview",
        transport=transport,
    )
    for _ in range(4):
        transport.enqueue(json_response({}))
    connector.chat_completion(
        deployment="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.5,
        max_tokens=50,
        tools=[{"type": "function"}],
        tool_choice="auto",
        response_format={"type": "json_object"},
        seed=42,
    )
    connector.embeddings(deployment="ada", input="hi", dimensions=128)
    connector.generate_image(
        deployment="dalle-3",
        prompt="cat",
        n=1,
        size="1024x1024",
        quality="hd",
        style="vivid",
        response_format="url",
    )
    connector.list_models()
    assert transport.requests[0].headers["api-key"] == "k"
    assert transport.requests[0].params["api-version"] == "2024-08-01-preview"
    with pytest.raises(ValueError):
        AzureOpenAIToolSet(endpoint="", api_key="x")
    with pytest.raises(ValueError):
        AzureOpenAIToolSet(endpoint="x", api_key="")
    with pytest.raises(ValueError):
        connector.chat_completion(deployment="", messages=[{}])
    with pytest.raises(ValueError):
        connector.embeddings(deployment="", input="x")
    with pytest.raises(ValueError):
        connector.generate_image(deployment="d", prompt="")


# MARK: - Agent-ready summary defaults


def test_anthropic_list_models_summaries() -> None:
    transport = MockTransport()
    connector = AnthropicToolSet(api_key="sk-ant", transport=transport)
    payload = {
        "data": [
            {"id": "claude-3-5-sonnet-latest", "display_name": "Sonnet", "created_at": 1},
            {"id": "claude-3-haiku-latest", "display_name": "Haiku", "created_at": 2},
        ],
        "has_more": False,
    }
    transport.enqueue(json_response(payload))
    result = connector.list_models()
    summaries = result["models"]
    assert summaries[0]["model_ref"] == "model_1"
    assert summaries[0]["model_name"] == "claude-3-5-sonnet-latest"
    assert summaries[0]["display_name"] == "Sonnet"
    assert "id" not in summaries[0]

    transport.enqueue(json_response(payload))
    with_ids = connector.list_models(include_ids=True)
    assert with_ids["models"][0]["id"] == "claude-3-5-sonnet-latest"


def test_anthropic_cancel_batch_accepts_dict() -> None:
    transport = MockTransport()
    connector = AnthropicToolSet(api_key="sk-ant", transport=transport)
    transport.enqueue(json_response({"id": "msgbatch_X", "processing_status": "canceling"}))
    connector.cancel_batch({"id": "msgbatch_X"})
    assert transport.requests[0].url.endswith("/v1/messages/batches/msgbatch_X/cancel")
    with pytest.raises(ValueError):
        connector.cancel_batch("")


def test_openai_list_models_summaries() -> None:
    transport = MockTransport()
    connector = AzureOpenAIToolSet  # noqa: F841 (sanity import)
    from maivn_tools.connectors.openai import OpenAIToolSet

    connector = OpenAIToolSet(api_key="sk-x", transport=transport)
    payload = {
        "data": [
            {"id": "gpt-4o-mini", "owned_by": "openai", "created": 10},
            {"id": "text-embedding-3-small", "owned_by": "openai", "created": 9},
        ]
    }
    transport.enqueue(json_response(payload))
    result = connector.list_models()
    summaries = result["models"]
    assert summaries[0]["model_ref"] == "model_1"
    assert summaries[0]["model_name"] == "gpt-4o-mini"
    assert "id" not in summaries[0]
    assert summaries[1]["model_ref"] == "model_2"

    transport.enqueue(json_response(payload))
    with_ids = connector.list_models(include_ids=True)
    assert with_ids["models"][0]["id"] == "gpt-4o-mini"


def test_openai_list_files_and_batches_summaries() -> None:
    from maivn_tools.connectors.openai import OpenAIToolSet

    transport = MockTransport()
    connector = OpenAIToolSet(api_key="sk-x", transport=transport)
    files_payload = {
        "data": [
            {
                "id": "file-abc",
                "filename": "train.jsonl",
                "purpose": "fine-tune",
                "bytes": 1024,
                "created_at": 1,
                "status": "processed",
            },
            {
                "id": "file-def",
                "filename": "val.jsonl",
                "purpose": "fine-tune",
                "bytes": 512,
                "created_at": 2,
                "status": "processed",
            },
        ]
    }
    transport.enqueue(json_response(files_payload))
    files_result = connector.list_files()
    assert files_result["files"][0]["file_ref"] == "file_1"
    assert files_result["files"][0]["filename"] == "train.jsonl"
    assert "file_id" not in files_result["files"][0]

    transport.enqueue(json_response(files_payload))
    with_ids = connector.list_files(include_ids=True)
    assert with_ids["files"][0]["file_id"] == "file-abc"

    batches_payload = {
        "data": [
            {
                "id": "batch_xyz",
                "endpoint": "/v1/chat/completions",
                "status": "in_progress",
                "request_counts": {"total": 10, "completed": 3, "failed": 0},
                "created_at": 100,
            }
        ],
        "has_more": False,
    }
    transport.enqueue(json_response(batches_payload))
    batches_result = connector.list_batches()
    assert batches_result["batches"][0]["batch_ref"] == "batch_1"
    assert "batch_id" not in batches_result["batches"][0]


def test_openai_list_fine_tuning_jobs_and_vector_stores_summaries() -> None:
    from maivn_tools.connectors.openai import OpenAIToolSet

    transport = MockTransport()
    connector = OpenAIToolSet(api_key="sk-x", transport=transport)
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "ftjob_1",
                        "model": "gpt-4o-mini-2024-07-18",
                        "fine_tuned_model": None,
                        "status": "running",
                        "created_at": 10,
                    }
                ],
                "has_more": False,
            }
        )
    )
    jobs_result = connector.list_fine_tuning_jobs()
    assert jobs_result["jobs"][0]["job_ref"] == "job_1"
    assert "job_id" not in jobs_result["jobs"][0]

    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "vs_1",
                        "name": "docs",
                        "file_counts": {"completed": 5, "in_progress": 0},
                        "status": "completed",
                        "created_at": 11,
                    }
                ],
                "has_more": False,
            }
        )
    )
    stores_result = connector.list_vector_stores()
    assert stores_result["vector_stores"][0]["store_ref"] == "store_1"
    assert "store_id" not in stores_result["vector_stores"][0]


def test_openai_delete_file_accepts_dict_input() -> None:
    from maivn_tools.connectors.openai import OpenAIToolSet

    transport = MockTransport()
    connector = OpenAIToolSet(api_key="sk-x", transport=transport)
    transport.enqueue(json_response({"deleted": True, "id": "file-1"}))
    transport.enqueue(json_response({"deleted": True, "id": "file-2"}))
    transport.enqueue(json_response({"deleted": True, "id": "file-3"}))
    # Raw id
    connector.delete_file("file-1")
    # Dict from list_files(include_ids=True)
    connector.delete_file({"file_id": "file-2", "filename": "x.jsonl"})
    # Dict that uses raw "id" key (eg from get_file)
    connector.delete_file({"id": "file-3"})
    assert transport.requests[0].url.endswith("/v1/files/file-1")
    assert transport.requests[1].url.endswith("/v1/files/file-2")
    assert transport.requests[2].url.endswith("/v1/files/file-3")
    with pytest.raises(ValueError):
        connector.delete_file({})
    with pytest.raises(ValueError):
        connector.delete_file(123)  # type: ignore[arg-type]


def test_openai_cancel_batch_accepts_dict_input() -> None:
    from maivn_tools.connectors.openai import OpenAIToolSet

    transport = MockTransport()
    connector = OpenAIToolSet(api_key="sk-x", transport=transport)
    transport.enqueue(json_response({"id": "batch_a", "status": "cancelling"}))
    transport.enqueue(json_response({"id": "batch_b", "status": "cancelling"}))
    connector.cancel_batch("batch_a")
    connector.cancel_batch({"batch_id": "batch_b"})
    assert transport.requests[0].url.endswith("/v1/batches/batch_a/cancel")
    assert transport.requests[1].url.endswith("/v1/batches/batch_b/cancel")


def test_gemini_list_models_summaries() -> None:
    transport = MockTransport()
    connector = GeminiToolSet(api_key="g", transport=transport)
    transport.enqueue(
        json_response(
            {
                "models": [
                    {
                        "name": "models/gemini-1.5-pro",
                        "displayName": "Gemini 1.5 Pro",
                        "supportedGenerationMethods": ["generateContent"],
                        "inputTokenLimit": 2000000,
                        "outputTokenLimit": 8192,
                    }
                ],
                "nextPageToken": None,
            }
        )
    )
    result = connector.list_models()
    assert result["models"][0]["model_ref"] == "model_1"
    assert result["models"][0]["model_name"] == "models/gemini-1.5-pro"
    assert "name" not in result["models"][0]


def test_azure_openai_list_models_summaries() -> None:
    transport = MockTransport()
    connector = AzureOpenAIToolSet(
        endpoint="https://x.openai.azure.com",
        api_key="k",
        transport=transport,
    )
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "gpt-4o",
                        "capabilities": {"chat_completion": True},
                        "lifecycle_status": "generally-available",
                    }
                ]
            }
        )
    )
    result = connector.list_models()
    assert result["models"][0]["model_ref"] == "model_1"
    assert result["models"][0]["model_name"] == "gpt-4o"
    assert "id" not in result["models"][0]


def test_bedrock_summaries() -> None:
    transport = MockTransport()
    connector = BedrockToolSet(region="us-east-1", transport=transport)
    transport.enqueue(
        json_response(
            {
                "modelSummaries": [
                    {
                        "modelId": "anthropic.claude-3-5-sonnet-20240620-v1:0",
                        "providerName": "Anthropic",
                        "inputModalities": ["TEXT"],
                        "outputModalities": ["TEXT"],
                        "modelArn": "arn:aws:bedrock:::foundation-model/x",
                    }
                ]
            }
        )
    )
    models = connector.list_foundation_models()
    assert models["models"][0]["model_ref"] == "model_1"
    assert models["models"][0]["provider"] == "Anthropic"
    assert "model_arn" not in models["models"][0]

    transport.enqueue(
        json_response(
            {
                "knowledgeBaseSummaries": [
                    {
                        "knowledgeBaseId": "kb1",
                        "name": "Docs",
                        "description": "docs",
                        "status": "ACTIVE",
                    }
                ]
            }
        )
    )
    kbs = connector.list_knowledge_bases()
    assert kbs["knowledge_bases"][0]["kb_ref"] == "kb_1"
    assert kbs["knowledge_bases"][0]["knowledge_base_id"] == "kb1"


def test_mistral_list_models_summaries() -> None:
    transport = MockTransport()
    connector = MistralToolSet(api_key="m", transport=transport)
    transport.enqueue(
        json_response(
            {
                "data": [
                    {"id": "mistral-large-latest", "owned_by": "mistralai", "created": 1},
                ]
            }
        )
    )
    result = connector.list_models()
    assert result["models"][0]["model_ref"] == "model_1"
    assert result["models"][0]["model_name"] == "mistral-large-latest"
    assert "id" not in result["models"][0]


def test_cohere_list_models_summaries() -> None:
    transport = MockTransport()
    connector = CohereToolSet(api_key="c", transport=transport)
    transport.enqueue(
        json_response(
            {
                "models": [
                    {
                        "name": "command-r-plus",
                        "endpoints": ["chat"],
                        "context_length": 128000,
                    }
                ],
                "next_page_token": None,
            }
        )
    )
    result = connector.list_models()
    assert result["models"][0]["model_ref"] == "model_1"
    assert result["models"][0]["model_name"] == "command-r-plus"
    assert "name" not in result["models"][0]


def test_huggingface_summaries() -> None:
    transport = MockTransport()
    connector = HuggingFaceToolSet(token="hf", transport=transport)
    transport.enqueue(
        json_response(
            [
                {
                    "id": "bert-base-uncased",
                    "pipeline_tag": "fill-mask",
                    "downloads": 100,
                    "likes": 5,
                    "lastModified": "2024-01-01",
                }
            ]
        )
    )
    models = connector.list_models()
    assert models["models"][0]["model_ref"] == "model_1"
    assert models["models"][0]["model_name"] == "bert-base-uncased"
    assert "id" not in models["models"][0]

    transport.enqueue(
        json_response(
            [
                {
                    "id": "squad",
                    "tags": ["language:english"],
                    "downloads": 50,
                    "lastModified": "2024-01-02",
                }
            ]
        )
    )
    datasets = connector.list_datasets()
    assert datasets["datasets"][0]["dataset_ref"] == "dataset_1"
    assert datasets["datasets"][0]["dataset_name"] == "squad"
    assert "id" not in datasets["datasets"][0]


def test_replicate_list_models_predictions_deployments() -> None:
    transport = MockTransport()
    connector = ReplicateToolSet(api_token="r8", transport=transport)
    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "owner": "meta",
                        "name": "llama-3",
                        "description": "llama",
                        "run_count": 10,
                        "visibility": "public",
                        "latest_version": {"id": "abcdef"},
                    }
                ]
            }
        )
    )
    models = connector.list_models()
    assert models["models"][0]["model_ref"] == "model_1"
    assert models["models"][0]["model_name"] == "meta/llama-3"
    assert "latest_version_id" not in models["models"][0]

    transport.enqueue(
        json_response(
            {
                "results": [
                    {"id": "pred_1", "version": "vx", "status": "succeeded"},
                ]
            }
        )
    )
    preds = connector.list_predictions()
    assert preds["predictions"][0]["prediction_ref"] == "prediction_1"
    assert "prediction_id" not in preds["predictions"][0]

    transport.enqueue(
        json_response(
            {
                "results": [
                    {
                        "owner": "me",
                        "name": "d1",
                        "current_release": {"version": "v1"},
                    }
                ]
            }
        )
    )
    deployments = connector.list_deployments()
    assert deployments["deployments"][0]["deployment_ref"] == "deployment_1"
    assert deployments["deployments"][0]["deployment_path"] == "me/d1"


def test_replicate_cancel_prediction_accepts_dict() -> None:
    transport = MockTransport()
    connector = ReplicateToolSet(api_token="r8", transport=transport)
    transport.enqueue(json_response({"id": "pred_1", "status": "canceled"}))
    connector.cancel_prediction({"id": "pred_1"})
    assert transport.requests[0].url.endswith("/v1/predictions/pred_1/cancel")


def test_elevenlabs_summaries() -> None:
    transport = MockTransport()
    connector = ElevenLabsToolSet(api_key="x", transport=transport)
    transport.enqueue(
        json_response(
            {
                "voices": [
                    {
                        "voice_id": "v1",
                        "name": "Rachel",
                        "category": "premade",
                        "labels": {"accent": "american"},
                    }
                ]
            }
        )
    )
    voices = connector.list_voices()
    assert voices["voices"][0]["voice_ref"] == "voice_1"
    # voice_id is always exposed because it's the user-facing handle.
    assert voices["voices"][0]["voice_id"] == "v1"
    assert "id" not in voices["voices"][0]

    transport.enqueue(
        json_response(
            [
                {
                    "model_id": "eleven_multilingual_v2",
                    "name": "Multilingual",
                    "languages": [{"language_id": "en"}, {"language_id": "es"}],
                    "can_do_text_to_speech": True,
                    "can_use_style": True,
                }
            ]
        )
    )
    models = connector.list_models()
    assert models["models"][0]["model_ref"] == "model_1"
    assert models["models"][0]["model_name"] == "eleven_multilingual_v2"
    assert models["models"][0]["languages"] == ["en", "es"]
    assert "model_id" not in models["models"][0]


def test_deepgram_list_projects_summaries() -> None:
    transport = MockTransport()
    connector = DeepgramToolSet(api_key="dg", transport=transport)
    transport.enqueue(
        json_response(
            {
                "projects": [
                    {"project_id": "p1", "name": "Demo", "company": "Acme"},
                ]
            }
        )
    )
    result = connector.list_projects()
    assert result["projects"][0]["project_ref"] == "project_1"
    assert "project_id" not in result["projects"][0]

    transport.enqueue(
        json_response(
            {
                "projects": [
                    {"project_id": "p1", "name": "Demo", "company": "Acme"},
                ]
            }
        )
    )
    with_ids = connector.list_projects(include_ids=True)
    assert with_ids["projects"][0]["project_id"] == "p1"


def test_assemblyai_list_transcripts_and_tolerant_delete() -> None:
    transport = MockTransport()
    connector = AssemblyAIToolSet(api_key="aai", transport=transport)
    transport.enqueue(
        json_response(
            {
                "transcripts": [
                    {
                        "id": "t1",
                        "status": "completed",
                        "audio_url": "https://x.wav",
                        "created": "2024-01-01",
                        "completed": "2024-01-02",
                    }
                ],
                "page_details": {},
            }
        )
    )
    result = connector.list_transcripts()
    assert result["transcripts"][0]["transcript_ref"] == "transcript_1"
    assert "transcript_id" not in result["transcripts"][0]

    transport.enqueue(json_response({"deleted": True}))
    transport.enqueue(json_response({"deleted": True}))
    connector.delete_transcript("t1")
    connector.delete_transcript({"transcript_id": "t2"})
    assert transport.requests[1].url.endswith("/v2/transcript/t1")
    assert transport.requests[2].url.endswith("/v2/transcript/t2")


def test_tavily_search_caps_max_results() -> None:
    transport = MockTransport()
    connector = TavilyToolSet(api_key="tvly", transport=transport)
    transport.enqueue(json_response({"results": []}))
    connector.search("ai", max_results=50)
    body = transport.requests[0].json_body
    assert body["max_results"] == 10
    with pytest.raises(ValueError):
        connector.search("ai", max_results=0)


def test_brave_search_caps_count() -> None:
    transport = MockTransport()
    connector = BraveSearchToolSet(api_key="b", transport=transport)
    transport.enqueue(json_response({}))
    connector.web_search("ai", count=50)
    assert transport.requests[0].params["count"] == 20
    transport.enqueue(json_response({}))
    connector.news_search("ai", count=99)
    assert transport.requests[1].params["count"] == 50
    transport.enqueue(json_response({}))
    connector.image_search("ai", count=33)
    assert transport.requests[2].params["count"] == 33
    transport.enqueue(json_response({}))
    connector.video_search("ai", count=33)
    assert transport.requests[3].params["count"] == 33
    transport.enqueue(json_response({}))
    connector.suggest("ai", count=33)
    assert transport.requests[4].params["count"] == 10
    with pytest.raises(ValueError):
        connector.web_search("ai", count=0)


def test_serpapi_search_caps_num() -> None:
    transport = MockTransport()
    connector = SerpAPIToolSet(api_key="sa", transport=transport)
    transport.enqueue(json_response({}))
    connector.search("ai", num=100)
    assert transport.requests[0].params["num"] == 10
    with pytest.raises(ValueError):
        connector.search("ai", num=0)


# MARK: - Destructive tagging


def test_destructive_tools_are_tagged() -> None:
    """Destructive tools must be filterable via exclude_tags=['destructive']."""
    from maivn_tools.connectors.anthropic import AnthropicToolSet
    from maivn_tools.connectors.assemblyai import AssemblyAIToolSet
    from maivn_tools.connectors.openai import OpenAIToolSet
    from maivn_tools.connectors.replicate import ReplicateToolSet

    cases = [
        (OpenAIToolSet, "delete_file"),
        (OpenAIToolSet, "delete_response"),
        (OpenAIToolSet, "delete_fine_tuned_model"),
        (OpenAIToolSet, "cancel_batch"),
        (OpenAIToolSet, "cancel_fine_tuning_job"),
        (OpenAIToolSet, "delete_vector_store"),
        (AnthropicToolSet, "cancel_batch"),
        (ReplicateToolSet, "cancel_prediction"),
        (AssemblyAIToolSet, "delete_transcript"),
    ]
    for cls, method_name in cases:
        method = getattr(cls, method_name)
        meta = getattr(method, "__maivn_toolify__", None)
        assert meta is not None, f"{cls.__name__}.{method_name} missing @toolify metadata"
        assert getattr(meta, "destructive", False), (
            f"{cls.__name__}.{method_name} should be destructive-tagged"
        )


def test_read_tools_are_filterable() -> None:
    """READ tools should be discoverable via toolify metadata."""
    from maivn_tools.connectors.openai import OpenAIToolSet
    from maivn_tools.connectors.tavily import TavilyToolSet

    read_cases = [
        (OpenAIToolSet, "list_models"),
        (OpenAIToolSet, "list_files"),
        (OpenAIToolSet, "list_batches"),
        (TavilyToolSet, "search"),
        (TavilyToolSet, "extract"),
    ]
    for cls, method_name in read_cases:
        method = getattr(cls, method_name)
        meta = getattr(method, "__maivn_toolify__", None)
        assert meta is not None, f"{cls.__name__}.{method_name} missing @toolify metadata"
        # Should NOT be destructive
        assert not getattr(meta, "destructive", False), (
            f"{cls.__name__}.{method_name} should not be destructive"
        )
