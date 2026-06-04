# pyright: strict
from __future__ import annotations

import pytest

from maivn_tools.connectors.openai import OpenAIToolSet
from maivn_tools.connectors.supabase import SupabaseToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Supabase


def _supabase() -> tuple[SupabaseToolSet, MockTransport]:
    transport = MockTransport()
    return (
        SupabaseToolSet(
            project_url="https://abc.supabase.co",
            api_key="anon-key",
            transport=transport,
        ),
        transport,
    )


def test_supabase_validates_inputs() -> None:
    with pytest.raises(ValueError):
        SupabaseToolSet(project_url="", api_key="k")
    with pytest.raises(ValueError):
        SupabaseToolSet(project_url="u", api_key="")


def test_supabase_select_sets_headers_and_filters() -> None:
    connector, transport = _supabase()
    transport.enqueue(json_response([{"id": 1}]))
    connector.select(
        "users",
        select="id,name",
        filter={"id": "eq.1"},
        order="id.desc",
        limit=10,
        offset=0,
        range_start=0,
        range_end=9,
        count="exact",
    )
    req = transport.requests[0]
    assert req.headers["apikey"] == "anon-key"
    assert req.headers["Authorization"] == "Bearer anon-key"
    assert req.headers["Accept-Profile"] == "public"
    assert req.headers["Range"] == "0-9"
    assert req.headers["Prefer"] == "count=exact"
    assert req.params["select"] == "id,name"
    assert req.params["id"] == "eq.1"
    with pytest.raises(ValueError):
        connector.select("")
    with pytest.raises(ValueError):
        connector.select("bad name")
    with pytest.raises(ValueError):
        connector.select("users", count="bogus")


def test_supabase_select_head_returns_no_body() -> None:
    connector, transport = _supabase()
    transport.enqueue(json_response([]))
    out = connector.select("users", head=True)
    assert transport.requests[0].method == "HEAD"
    assert "status" in out


def test_supabase_insert_update_delete() -> None:
    connector, transport = _supabase()
    transport.enqueue(json_response([{"id": 1}]))
    transport.enqueue(json_response([{"id": 1}]))
    transport.enqueue(json_response([{"id": 1}]))
    transport.enqueue(json_response({}))
    connector.insert("users", [{"name": "a"}], upsert=True, on_conflict="email")
    connector.insert("users", {"name": "b"})
    connector.update("users", filter={"id": "eq.1"}, values={"name": "c"})
    connector.delete("users", filter={"id": "eq.1"})
    insert_headers = transport.requests[0].headers
    assert "return=representation" in insert_headers["Prefer"]
    assert "resolution=merge-duplicates" in insert_headers["Prefer"]
    assert transport.requests[0].params == {"on_conflict": "email"}
    assert transport.requests[2].method == "PATCH"
    assert transport.requests[3].method == "DELETE"
    with pytest.raises(ValueError):
        connector.insert("users", [])
    with pytest.raises(ValueError):
        connector.update("users", filter={}, values={"x": 1})
    with pytest.raises(ValueError):
        connector.update("users", filter={"id": "eq.1"}, values={})
    with pytest.raises(ValueError):
        connector.delete("users", filter={})


def test_supabase_rpc_and_match_vectors() -> None:
    connector, transport = _supabase()
    transport.enqueue(json_response({"ok": True}))
    transport.enqueue(json_response([{"id": 1}]))
    connector.rpc("compute_score", args={"x": 1})
    connector.match_vectors(
        function_name="match_documents",
        embedding=[0.1, 0.2],
        match_count=5,
        match_threshold=0.7,
        extra_args={"category": "docs"},
    )
    body = transport.requests[1].json_body
    assert body["query_embedding"] == [0.1, 0.2]
    assert body["match_threshold"] == 0.7
    assert body["category"] == "docs"
    with pytest.raises(ValueError):
        connector.rpc("")
    with pytest.raises(ValueError):
        connector.match_vectors(function_name="match_x", embedding=[])


def test_supabase_auth_admin() -> None:
    connector, transport = _supabase()
    for _ in range(5):
        transport.enqueue(json_response({}))
    connector.list_users()
    connector.get_user("u1")
    connector.create_user(email="x@y", password="p", email_confirm=True)
    connector.update_user("u1", {"email": "a@b"})
    connector.delete_user("u1")
    assert transport.requests[2].json_body["email_confirm"] is True
    assert transport.requests[4].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_user("")
    with pytest.raises(ValueError):
        connector.create_user()
    with pytest.raises(ValueError):
        connector.update_user("", {"x": 1})
    with pytest.raises(ValueError):
        connector.update_user("u1", {})
    with pytest.raises(ValueError):
        connector.delete_user("")


def test_supabase_invite_and_storage() -> None:
    connector, transport = _supabase()
    for _ in range(6):
        transport.enqueue(json_response({}))
    connector.invite_user("user@x.test", data={"role": "admin"})
    connector.list_buckets()
    connector.create_bucket(bucket_id="docs", public=True, allowed_mime_types=["application/pdf"])
    connector.delete_bucket("docs")
    connector.list_objects("docs", prefix="2026/", limit=10)
    connector.create_signed_url("docs", "report.pdf", expires_in=600, download=True)
    assert transport.requests[4].json_body["prefix"] == "2026/"
    assert transport.requests[5].json_body["download"] is True
    with pytest.raises(ValueError):
        connector.invite_user("")
    with pytest.raises(ValueError):
        connector.create_bucket(bucket_id="")
    with pytest.raises(ValueError):
        connector.delete_bucket("")
    with pytest.raises(ValueError):
        connector.list_objects("")
    with pytest.raises(ValueError):
        connector.create_signed_url("docs", "")


def test_supabase_delete_object_and_invoke_function() -> None:
    connector, transport = _supabase()
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"output": "ok"}))
    connector.delete_object("docs", "old.pdf")
    out = connector.invoke_function("transcribe", body={"audio_url": "s3://"})
    assert transport.requests[0].method == "DELETE"
    assert out["body"]["output"] == "ok"
    with pytest.raises(ValueError):
        connector.delete_object("docs", "")
    with pytest.raises(ValueError):
        connector.invoke_function("")


# MARK: - Agent-ready summary defaults


def test_supabase_list_users_concise_summaries() -> None:
    """Agent-ready: list_users returns user_ref + user-facing fields by default."""
    connector, transport = _supabase()
    transport.enqueue(
        json_response(
            {
                "users": [
                    {
                        "id": "uuid-1",
                        "email": "a@example.com",
                        "role": "authenticated",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    {
                        "id": "uuid-2",
                        "email": "b@example.com",
                        "role": "authenticated",
                        "created_at": "2026-01-02T00:00:00Z",
                    },
                ],
                "total": 2,
            }
        )
    )
    result = connector.list_users()
    assert result["users"][0]["user_ref"] == "user_1"
    assert result["users"][0]["email"] == "a@example.com"
    # Raw provider IDs hidden by default.
    assert "user_id" not in result["users"][0]
    assert result["total"] == 2


def test_supabase_list_users_include_ids_opt_in() -> None:
    """include_ids=True returns the raw GoTrue user UUID for follow-up tools."""
    connector, transport = _supabase()
    transport.enqueue(json_response({"users": [{"id": "uuid-1", "email": "a@x"}], "total": 1}))
    result = connector.list_users(include_ids=True)
    assert result["users"][0]["user_id"] == "uuid-1"


def test_supabase_list_users_raw_mode() -> None:
    """include_metadata=False returns the raw GoTrue payload untouched."""
    connector, transport = _supabase()
    raw = {"users": [{"id": "uuid-1", "email": "a@x"}], "total": 1}
    transport.enqueue(json_response(raw))
    result = connector.list_users(include_metadata=False)
    assert result == raw


def test_supabase_list_buckets_concise_summaries() -> None:
    connector, transport = _supabase()
    transport.enqueue(
        json_response(
            [
                {"id": "docs", "name": "docs", "public": True, "file_size_limit": 1024},
                {"id": "media", "name": "media", "public": False},
            ]
        )
    )
    result = connector.list_buckets()
    assert isinstance(result, dict)
    assert result["buckets"][0]["bucket_ref"] == "bucket_1"
    # User-facing bucket id preserved.
    assert result["buckets"][0]["bucket_id"] == "docs"
    assert result["buckets"][0]["public"] is True


def test_supabase_list_objects_concise_summaries() -> None:
    connector, transport = _supabase()
    transport.enqueue(
        json_response(
            [
                {
                    "name": "report.pdf",
                    "metadata": {"size": 4096, "mimetype": "application/pdf"},
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ]
        )
    )
    result = connector.list_objects("docs")
    assert isinstance(result, dict)
    assert result["objects"][0]["object_ref"] == "object_1"
    # User-facing object name preserved.
    assert result["objects"][0]["name"] == "report.pdf"
    assert result["objects"][0]["size"] == 4096
    assert result["bucket_id"] == "docs"


def test_supabase_delete_user_accepts_dict_from_list() -> None:
    """Tolerant input: delete_user accepts a dict from list_users(include_ids=True)."""
    connector, transport = _supabase()
    transport.enqueue(json_response({}))
    candidate = {"user_id": "uuid-1", "email": "a@x"}
    result = connector.delete_user(candidate)
    assert result == {"id": "uuid-1", "deleted": True}
    assert transport.requests[0].url.endswith("/auth/v1/admin/users/uuid-1")


def test_supabase_update_user_accepts_dict_from_list() -> None:
    """Tolerant input: update_user accepts a dict from list_users."""
    connector, transport = _supabase()
    transport.enqueue(json_response({"id": "uuid-1"}))
    candidate = {"user_id": "uuid-1", "email": "a@x"}
    connector.update_user(candidate, {"email": "b@x"})
    assert transport.requests[0].url.endswith("/auth/v1/admin/users/uuid-1")


def test_supabase_delete_object_accepts_bucket_dict() -> None:
    """Tolerant input: delete_object accepts a bucket dict from list_buckets."""
    connector, transport = _supabase()
    transport.enqueue(json_response({}))
    bucket = {"bucket_id": "docs", "name": "docs"}
    result = connector.delete_object(bucket, "old.pdf")
    assert result["bucket"] == "docs"
    assert transport.requests[0].url.endswith("/storage/v1/object/docs/old.pdf")


def test_supabase_destructive_tags() -> None:
    """Agent-ready: destructive ops carry destructive=True."""
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _supabase()
    destructive_methods = [
        connector.delete,
        connector.delete_user,
        connector.delete_bucket,
        connector.delete_object,
    ]
    for method in destructive_methods:
        opts = get_toolify_options(method)
        assert opts is not None
        assert opts.destructive is True
    # Reads stay non-destructive.
    read_methods = [
        connector.select,
        connector.match_vectors,
        connector.list_users,
        connector.get_user,
        connector.list_buckets,
        connector.list_objects,
    ]
    for method in read_methods:
        opts = get_toolify_options(method)
        assert opts is not None
        assert opts.destructive is False


# MARK: - OpenAI


def _openai() -> tuple[OpenAIToolSet, MockTransport]:
    transport = MockTransport()
    return OpenAIToolSet(api_key="sk-xxx", transport=transport), transport


def test_openai_requires_api_key() -> None:
    with pytest.raises(ValueError):
        OpenAIToolSet(api_key="")


def test_openai_chat_completion() -> None:
    connector, transport = _openai()
    transport.enqueue(json_response({"choices": []}))
    connector.chat_completion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.5,
        max_completion_tokens=100,
        tools=[{"type": "function", "function": {"name": "x"}}],
        tool_choice="auto",
        response_format={"type": "json_object"},
        seed=42,
        stop=["END"],
    )
    body = transport.requests[0].json_body
    assert body["model"] == "gpt-4o-mini"
    assert body["seed"] == 42
    assert body["stop"] == ["END"]
    assert transport.requests[0].headers["Authorization"] == "Bearer sk-xxx"
    with pytest.raises(ValueError):
        connector.chat_completion(model="", messages=[{"role": "user", "content": "x"}])
    with pytest.raises(ValueError):
        connector.chat_completion(model="m", messages=[])


def test_openai_responses() -> None:
    connector, transport = _openai()
    transport.enqueue(json_response({"id": "resp_1"}))
    transport.enqueue(json_response({"id": "resp_1"}))
    transport.enqueue(json_response({}))
    connector.responses_create(model="gpt-4.1", input="hi", instructions="be brief", store=True)
    connector.get_response("resp_1")
    connector.delete_response("resp_1")
    assert transport.requests[0].json_body["instructions"] == "be brief"
    assert transport.requests[2].method == "DELETE"
    with pytest.raises(ValueError):
        connector.responses_create(model="", input="x")
    with pytest.raises(ValueError):
        connector.get_response("")
    with pytest.raises(ValueError):
        connector.delete_response("")


def test_openai_embeddings_and_moderation() -> None:
    connector, transport = _openai()
    transport.enqueue(json_response({"data": []}))
    transport.enqueue(json_response({"results": []}))
    connector.create_embedding(
        model="text-embedding-3-small",
        input=["hi"],
        encoding_format="float",
        dimensions=256,
    )
    connector.moderate(input="hello", model="omni-moderation-latest")
    with pytest.raises(ValueError):
        connector.create_embedding(model="", input="x")
    with pytest.raises(ValueError):
        connector.create_embedding(model="m", input="x", encoding_format="bogus")


def test_openai_models() -> None:
    connector, transport = _openai()
    transport.enqueue(json_response({"data": []}))
    transport.enqueue(json_response({"id": "m"}))
    transport.enqueue(json_response({"deleted": True}))
    connector.list_models()
    connector.get_model("gpt-4o-mini")
    connector.delete_fine_tuned_model("ft:gpt-4o-mini:org::abc")
    assert transport.requests[2].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_model("")
    with pytest.raises(ValueError):
        connector.delete_fine_tuned_model("")


def test_openai_images_and_speech() -> None:
    connector, transport = _openai()
    transport.enqueue(json_response({"data": []}))
    transport.enqueue(json_response({}))
    connector.generate_image(
        model="gpt-image-1",
        prompt="A cat",
        n=1,
        size="1024x1024",
        quality="high",
        style="vivid",
    )
    out = connector.speech(model="gpt-4o-mini-tts", voice="alloy", input="hello")
    assert "status" in out
    with pytest.raises(ValueError):
        connector.generate_image(model="", prompt="x")
    with pytest.raises(ValueError):
        connector.speech(model="m", voice="", input="x")


def test_openai_files_batches_finetune_vector_stores() -> None:
    connector, transport = _openai()
    for _ in range(12):
        transport.enqueue(json_response({"id": "x"}))
    connector.list_files(purpose="batch")
    connector.get_file("file-1")
    connector.delete_file("file-1")
    connector.create_batch(input_file_id="file-1", endpoint="/v1/chat/completions")
    connector.list_batches(after="b1", limit=10)
    connector.get_batch("b1")
    connector.cancel_batch("b1")
    connector.create_fine_tuning_job(training_file="file-1", model="gpt-4o-mini-2024-07-18")
    connector.list_fine_tuning_jobs()
    connector.cancel_fine_tuning_job("ft1")
    connector.create_vector_store(name="docs", file_ids=["file-1"])
    connector.list_vector_stores()
    assert transport.requests[0].params == {"purpose": "batch"}
    assert transport.requests[2].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_file("")
    with pytest.raises(ValueError):
        connector.delete_file("")
    with pytest.raises(ValueError):
        connector.create_batch(input_file_id="", endpoint="x")
    with pytest.raises(ValueError):
        connector.get_batch("")
    with pytest.raises(ValueError):
        connector.cancel_batch("")
    with pytest.raises(ValueError):
        connector.create_fine_tuning_job(training_file="", model="m")
    with pytest.raises(ValueError):
        connector.cancel_fine_tuning_job("")
    with pytest.raises(ValueError):
        connector.create_vector_store(name="")


def test_openai_vector_store_lifecycle_more() -> None:
    connector, transport = _openai()
    transport.enqueue(json_response({"id": "vs"}))
    transport.enqueue(json_response({}))
    connector.get_vector_store("vs1")
    connector.delete_vector_store("vs1")
    assert transport.requests[1].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_vector_store({})
    with pytest.raises(ValueError):
        connector.delete_vector_store({})


# MARK: - OpenAI agent-ready summaries


def test_openai_list_models_returns_summaries_with_ref() -> None:
    connector, transport = _openai()
    payload = {
        "data": [
            {"id": "gpt-4o-mini", "owned_by": "openai", "created": 1},
            {"id": "text-embedding-3-small", "owned_by": "openai", "created": 2},
        ]
    }
    transport.enqueue(json_response(payload))
    result = connector.list_models()
    assert "models" in result
    assert result["models"][0]["model_ref"] == "model_1"
    assert result["models"][0]["model_name"] == "gpt-4o-mini"
    # Raw id omitted by default
    assert "id" not in result["models"][0]
    transport.enqueue(json_response(payload))
    with_ids = connector.list_models(include_ids=True)
    assert with_ids["models"][0]["id"] == "gpt-4o-mini"


def test_openai_list_files_summaries_and_tolerant_delete() -> None:
    connector, transport = _openai()
    payload = {
        "data": [
            {
                "id": "file-1",
                "filename": "a.jsonl",
                "purpose": "batch",
                "bytes": 100,
                "created_at": 1,
                "status": "processed",
            },
            {
                "id": "file-2",
                "filename": "b.jsonl",
                "purpose": "batch",
                "bytes": 200,
                "created_at": 2,
                "status": "processed",
            },
        ]
    }
    transport.enqueue(json_response(payload))
    result = connector.list_files()
    assert result["files"][0]["file_ref"] == "file_1"
    assert "file_id" not in result["files"][0]

    transport.enqueue(json_response(payload))
    with_ids = connector.list_files(include_ids=True)
    assert with_ids["files"][0]["file_id"] == "file-1"

    # delete_file accepts the dict directly
    transport.enqueue(json_response({"id": "file-1", "deleted": True}))
    connector.delete_file({"file_id": "file-1", "filename": "a.jsonl"})
    assert transport.requests[2].url.endswith("/v1/files/file-1")

    # get_file accepts the list-shaped dict response too
    transport.enqueue(json_response({"id": "file-1"}))
    connector.get_file(payload)
    assert transport.requests[3].url.endswith("/v1/files/file-1")


def test_openai_list_batches_summaries_and_tolerant_cancel() -> None:
    connector, transport = _openai()
    payload = {
        "data": [
            {
                "id": "batch_a",
                "endpoint": "/v1/chat/completions",
                "status": "in_progress",
                "request_counts": {"total": 5, "completed": 0, "failed": 0},
                "created_at": 99,
            }
        ],
        "has_more": False,
    }
    transport.enqueue(json_response(payload))
    result = connector.list_batches()
    assert result["batches"][0]["batch_ref"] == "batch_1"
    assert "batch_id" not in result["batches"][0]

    transport.enqueue(json_response({"id": "batch_a", "status": "cancelling"}))
    connector.cancel_batch({"id": "batch_a"})
    assert transport.requests[1].url.endswith("/v1/batches/batch_a/cancel")


def test_openai_list_fine_tuning_jobs_summaries() -> None:
    connector, transport = _openai()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "ftjob_1",
                        "model": "gpt-4o-mini-2024-07-18",
                        "fine_tuned_model": None,
                        "status": "running",
                        "created_at": 1,
                    }
                ],
                "has_more": False,
            }
        )
    )
    result = connector.list_fine_tuning_jobs()
    assert result["jobs"][0]["job_ref"] == "job_1"
    assert "job_id" not in result["jobs"][0]


def test_openai_list_vector_stores_summaries() -> None:
    connector, transport = _openai()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "vs_1",
                        "name": "docs",
                        "file_counts": {"completed": 1, "in_progress": 0},
                        "status": "completed",
                        "created_at": 1,
                    }
                ],
                "has_more": False,
            }
        )
    )
    result = connector.list_vector_stores()
    assert result["vector_stores"][0]["store_ref"] == "store_1"
    assert "store_id" not in result["vector_stores"][0]


def test_openai_create_batch_accepts_file_dict() -> None:
    connector, transport = _openai()
    transport.enqueue(json_response({"id": "batch_1"}))
    connector.create_batch(
        input_file_id={"file_id": "file-x", "filename": "in.jsonl"},
        endpoint="/v1/chat/completions",
    )
    body = transport.requests[0].json_body
    assert body["input_file_id"] == "file-x"


def test_openai_create_vector_store_accepts_file_dicts() -> None:
    connector, transport = _openai()
    transport.enqueue(json_response({"id": "vs1"}))
    connector.create_vector_store(
        name="docs",
        file_ids=["file-1", {"file_id": "file-2"}, {"id": "file-3"}],
    )
    body = transport.requests[0].json_body
    assert body["file_ids"] == ["file-1", "file-2", "file-3"]
