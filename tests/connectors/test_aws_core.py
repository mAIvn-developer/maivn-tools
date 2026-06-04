"""Tests for AWS core connectors.

S3, Lambda, CloudWatch Logs, IAM.
"""

# pyright: strict
from __future__ import annotations

import pytest

from maivn_tools.connectors.aws_cloudwatch_logs import (
    AmazonCloudWatchLogsToolSet,
)
from maivn_tools.connectors.aws_iam import AmazonIAMToolSet
from maivn_tools.connectors.aws_lambda import AmazonLambdaToolSet
from maivn_tools.connectors.aws_s3 import AmazonS3ToolSet
from maivn_tools.testing import MockTransport, json_response, text_response

# MARK: - S3


def _s3() -> tuple[AmazonS3ToolSet, MockTransport]:
    transport = MockTransport()
    return (
        AmazonS3ToolSet(
            access_key="AKIA",
            secret_key="ss",
            region="us-east-1",
            transport=transport,
        ),
        transport,
    )


def test_s3_requires_args() -> None:
    with pytest.raises(ValueError):
        AmazonS3ToolSet(access_key="", secret_key="s")
    with pytest.raises(ValueError):
        AmazonS3ToolSet(access_key="a", secret_key="")


def test_s3_endpoints() -> None:
    connector, transport = _s3()
    for _ in range(11):
        transport.enqueue(text_response("<xml/>"))
    connector.list_buckets()
    connector.create_bucket("mybucket", location_constraint="us-west-2")
    connector.delete_bucket("mybucket")
    connector.list_objects_v2(
        "mybucket",
        prefix="x/",
        delimiter="/",
        max_keys=100,
        continuation_token="ct",
        start_after="x/y",
    )
    connector.head_object(bucket="mybucket", key="x/y", version_id="v")
    connector.get_object(
        bucket="mybucket",
        key="x/y",
        version_id="v",
        range_header="bytes=0-99",
    )
    connector.put_object(
        bucket="mybucket",
        key="x/y",
        body=b"hello",
        content_type="text/plain",
        metadata={"k": "v"},
        acl="private",
        cache_control="max-age=60",
    )
    connector.delete_object(bucket="mybucket", key="x/y", version_id="v")
    connector.copy_object(
        source_bucket="src",
        source_key="a",
        dest_bucket="dst",
        dest_key="b",
        metadata_directive="REPLACE",
    )
    connector.get_bucket_location("mybucket")
    connector.get_bucket_policy("mybucket")
    assert "Authorization" in transport.requests[0].headers
    assert transport.requests[0].headers["Authorization"].startswith("AWS4-HMAC-SHA256")
    assert "x-amz-date" in transport.requests[0].headers
    assert transport.requests[1].method == "PUT"
    assert transport.requests[2].method == "DELETE"
    assert transport.requests[7].method == "DELETE"
    with pytest.raises(ValueError):
        connector.create_bucket("")
    with pytest.raises(ValueError):
        connector.delete_bucket("")
    with pytest.raises(ValueError):
        connector.list_objects_v2("")
    with pytest.raises(ValueError):
        connector.head_object(bucket="", key="x")
    with pytest.raises(ValueError):
        connector.get_object(bucket="", key="x")
    with pytest.raises(ValueError):
        connector.put_object(bucket="", key="x", body=b"")
    with pytest.raises(ValueError):
        connector.delete_object(bucket="", key="x")
    with pytest.raises(ValueError):
        connector.copy_object(
            source_bucket="",
            source_key="a",
            dest_bucket="b",
            dest_key="c",
        )
    with pytest.raises(ValueError):
        connector.get_bucket_location("")
    with pytest.raises(ValueError):
        connector.get_bucket_policy("")


# MARK: - Lambda


def _lambda() -> tuple[AmazonLambdaToolSet, MockTransport]:
    transport = MockTransport()
    return (
        AmazonLambdaToolSet(
            access_key="AKIA",
            secret_key="ss",
            region="us-east-1",
            transport=transport,
        ),
        transport,
    )


def test_lambda_requires_args() -> None:
    with pytest.raises(ValueError):
        AmazonLambdaToolSet(access_key="", secret_key="s")
    with pytest.raises(ValueError):
        AmazonLambdaToolSet(access_key="a", secret_key="")


def test_lambda_endpoints() -> None:
    connector, transport = _lambda()
    for _ in range(10):
        transport.enqueue(json_response({"FunctionName": "f"}))
    connector.list_functions(max_items=10, marker="m", function_version="ALL")
    connector.get_function("myfn", qualifier="$LATEST")
    connector.invoke_function(
        "myfn",
        payload={"k": "v"},
        invocation_type="RequestResponse",
        log_type="Tail",
        qualifier="$LATEST",
    )
    connector.update_function_configuration(
        "myfn",
        environment={"Variables": {"K": "V"}},
        timeout=30,
        memory_size=256,
        handler="app.handler",
        role="arn:aws:iam::1:role/r",
    )
    connector.update_function_code(
        "myfn",
        zip_file=b"zip",
        publish=True,
    )
    connector.delete_function("myfn", qualifier="$LATEST")
    connector.list_versions("myfn", max_items=10, marker="m")
    connector.publish_version("myfn", description="D", code_sha256="sha")
    connector.list_aliases("myfn", max_items=10, marker="m")
    connector.put_function_concurrency(
        "myfn",
        reserved_concurrent_executions=10,
    )
    assert transport.requests[5].method == "DELETE"
    with pytest.raises(ValueError):
        connector.get_function("")
    with pytest.raises(ValueError):
        connector.invoke_function("")
    with pytest.raises(ValueError):
        connector.invoke_function("f", invocation_type="bogus")
    with pytest.raises(ValueError):
        connector.update_function_configuration("")
    with pytest.raises(ValueError):
        connector.update_function_configuration("f")
    with pytest.raises(ValueError):
        connector.update_function_code("")
    with pytest.raises(ValueError):
        connector.update_function_code("f")
    with pytest.raises(ValueError):
        connector.delete_function("")
    with pytest.raises(ValueError):
        connector.list_versions("")
    with pytest.raises(ValueError):
        connector.publish_version("")
    with pytest.raises(ValueError):
        connector.list_aliases("")
    with pytest.raises(ValueError):
        connector.put_function_concurrency("", reserved_concurrent_executions=1)


# MARK: - CloudWatch Logs


def _cwl() -> tuple[AmazonCloudWatchLogsToolSet, MockTransport]:
    transport = MockTransport()
    return (
        AmazonCloudWatchLogsToolSet(
            access_key="AKIA",
            secret_key="ss",
            region="us-east-1",
            transport=transport,
        ),
        transport,
    )


def test_cwl_requires_args() -> None:
    with pytest.raises(ValueError):
        AmazonCloudWatchLogsToolSet(access_key="", secret_key="s")


def test_cwl_endpoints() -> None:
    connector, transport = _cwl()
    for _ in range(10):
        transport.enqueue(json_response({"logGroups": []}))
    connector.describe_log_groups(
        log_group_name_prefix="/aws/",
        limit=10,
        next_token="nt",
    )
    connector.create_log_group(
        log_group_name="/x",
        tags={"t": "v"},
        kms_key_id="kms",
    )
    connector.delete_log_group(log_group_name="/x")
    connector.put_retention_policy(log_group_name="/x", retention_in_days=14)
    connector.describe_log_streams(
        log_group_name="/x",
        log_stream_name_prefix="a",
        order_by="LogStreamName",
        descending=True,
        limit=10,
        next_token="nt",
    )
    connector.get_log_events(
        log_group_name="/x",
        log_stream_name="s",
        start_time=1,
        end_time=2,
        next_token="nt",
        limit=10,
        start_from_head=False,
    )
    connector.filter_log_events(
        log_group_name="/x",
        filter_pattern="ERROR",
        start_time=1,
        end_time=2,
        next_token="nt",
        limit=10,
    )
    connector.put_log_events(
        log_group_name="/x",
        log_stream_name="s",
        log_events=[{"timestamp": 1, "message": "hi"}],
        sequence_token="st",
    )
    connector.start_query(
        query_string="fields @timestamp",
        start_time=1,
        end_time=2,
        log_group_names=["/x"],
        limit=100,
    )
    connector.get_query_results(query_id="q1")
    assert transport.requests[0].headers["X-Amz-Target"] == "Logs_20140328.DescribeLogGroups"
    with pytest.raises(ValueError):
        connector.create_log_group(log_group_name="")
    with pytest.raises(ValueError):
        connector.delete_log_group(log_group_name="")
    with pytest.raises(ValueError):
        connector.put_retention_policy(log_group_name="", retention_in_days=1)
    with pytest.raises(ValueError):
        connector.describe_log_streams(log_group_name="")
    with pytest.raises(ValueError):
        connector.describe_log_streams(log_group_name="x", order_by="bogus")
    with pytest.raises(ValueError):
        connector.get_log_events(log_group_name="", log_stream_name="s")
    with pytest.raises(ValueError):
        connector.filter_log_events(log_group_name="")
    with pytest.raises(ValueError):
        connector.put_log_events(
            log_group_name="",
            log_stream_name="s",
            log_events=[{"x": 1}],
        )
    with pytest.raises(ValueError):
        connector.start_query(query_string="", start_time=1, end_time=2)
    with pytest.raises(ValueError):
        connector.start_query(query_string="x", start_time=1, end_time=2)
    with pytest.raises(ValueError):
        connector.get_query_results(query_id="")


# MARK: - IAM


def _iam() -> tuple[AmazonIAMToolSet, MockTransport]:
    transport = MockTransport()
    return (
        AmazonIAMToolSet(
            access_key="AKIA",
            secret_key="ss",
            transport=transport,
        ),
        transport,
    )


def test_iam_requires_args() -> None:
    with pytest.raises(ValueError):
        AmazonIAMToolSet(access_key="", secret_key="s")
    with pytest.raises(ValueError):
        AmazonIAMToolSet(access_key="a", secret_key="")


def test_iam_endpoints() -> None:
    connector, transport = _iam()
    for _ in range(14):
        transport.enqueue(json_response({"Users": []}))
    connector.list_users(path_prefix="/", max_items=10, marker="m")
    connector.get_user(user_name="alice")
    connector.create_user(
        user_name="bob",
        path="/",
        permissions_boundary="arn:...",
    )
    connector.delete_user("bob")
    connector.list_roles(path_prefix="/", max_items=10, marker="m")
    connector.get_role("MyRole")
    connector.create_role(
        role_name="R",
        assume_role_policy_document="{}",
        description="d",
        max_session_duration=3600,
    )
    connector.delete_role("R")
    connector.list_policies(
        scope="Local",
        only_attached=True,
        max_items=10,
        marker="m",
    )
    connector.get_policy("arn:aws:iam::1:policy/p")
    connector.attach_user_policy(user_name="bob", policy_arn="arn:p")
    connector.attach_role_policy(role_name="R", policy_arn="arn:p")
    connector.detach_user_policy(user_name="bob", policy_arn="arn:p")
    connector.create_access_key(user_name="bob")
    auth = transport.requests[0].headers["Authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256")
    assert transport.requests[0].method == "POST"
    with pytest.raises(ValueError):
        connector.create_user(user_name="")
    with pytest.raises(ValueError):
        connector.delete_user("")
    with pytest.raises(ValueError):
        connector.get_role("")
    with pytest.raises(ValueError):
        connector.create_role(role_name="", assume_role_policy_document="{}")
    with pytest.raises(ValueError):
        connector.create_role(role_name="r", assume_role_policy_document="")
    with pytest.raises(ValueError):
        connector.delete_role("")
    with pytest.raises(ValueError):
        connector.list_policies(scope="bogus")
    with pytest.raises(ValueError):
        connector.get_policy("")
    with pytest.raises(ValueError):
        connector.attach_user_policy(user_name="", policy_arn="p")
    with pytest.raises(ValueError):
        connector.attach_role_policy(role_name="r", policy_arn="")
    with pytest.raises(ValueError):
        connector.detach_user_policy(user_name="", policy_arn="p")
    with pytest.raises(ValueError):
        connector.create_access_key(user_name="")


def test_iam_delete_access_key() -> None:
    connector, transport = _iam()
    transport.enqueue(json_response({"DeleteAccessKeyResponse": {}}))
    connector.delete_access_key(user_name="bob", access_key_id="AKIA1234")
    with pytest.raises(ValueError):
        connector.delete_access_key(user_name="", access_key_id="x")
    with pytest.raises(ValueError):
        connector.delete_access_key(user_name="b", access_key_id="")


# MARK: - Agent-ready summaries (S3)


_S3_LIST_BUCKETS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<ListAllMyBucketsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    "<Buckets>"
    "<Bucket>"
    "<Name>my-data-bucket</Name>"
    "<CreationDate>2026-01-01T00:00:00.000Z</CreationDate>"
    "</Bucket>"
    "<Bucket>"
    "<Name>my-logs-bucket</Name>"
    "<CreationDate>2026-02-01T00:00:00.000Z</CreationDate>"
    "</Bucket>"
    "</Buckets>"
    "</ListAllMyBucketsResult>"
)


_S3_LIST_OBJECTS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    "<Name>my-data-bucket</Name>"
    "<IsTruncated>true</IsTruncated>"
    "<NextContinuationToken>tok-123</NextContinuationToken>"
    "<Contents>"
    "<Key>folder/file-a.txt</Key>"
    "<LastModified>2026-05-16T00:00:00.000Z</LastModified>"
    '<ETag>"abc"</ETag>'
    "<Size>1024</Size>"
    "<StorageClass>STANDARD</StorageClass>"
    "</Contents>"
    "<Contents>"
    "<Key>folder/file-b.txt</Key>"
    "<LastModified>2026-05-16T00:00:01.000Z</LastModified>"
    '<ETag>"def"</ETag>'
    "<Size>2048</Size>"
    "<StorageClass>STANDARD</StorageClass>"
    "</Contents>"
    "</ListBucketResult>"
)


def test_s3_list_buckets_summary() -> None:
    connector, transport = _s3()
    transport.enqueue(text_response(_S3_LIST_BUCKETS_XML))
    result = connector.list_buckets()
    assert "buckets" in result
    assert result["buckets"][0]["bucket_ref"] == "bucket_1"
    assert result["buckets"][0]["name"] == "my-data-bucket"
    assert result["buckets"][1]["name"] == "my-logs-bucket"


def test_s3_list_buckets_raw_passthrough() -> None:
    connector, transport = _s3()
    transport.enqueue(text_response(_S3_LIST_BUCKETS_XML))
    result = connector.list_buckets(include_metadata=False)
    assert "body" in result
    assert "my-data-bucket" in result["body"]


def test_s3_list_objects_v2_summary() -> None:
    connector, transport = _s3()
    transport.enqueue(text_response(_S3_LIST_OBJECTS_XML))
    result = connector.list_objects_v2("my-data-bucket", prefix="folder/")
    assert result["bucket"] == "my-data-bucket"
    assert result["objects"][0]["object_ref"] == "object_1"
    assert result["objects"][0]["key"] == "folder/file-a.txt"
    assert result["objects"][0]["size"] == 1024
    assert result["objects"][0]["etag"] == "abc"
    assert result["is_truncated"] is True
    assert result["next_continuation_token"] == "tok-123"


def test_s3_destructive_tools_marked() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _s3()
    delete_opts = get_toolify_options(connector.delete_object)
    bucket_opts = get_toolify_options(connector.delete_bucket)
    assert delete_opts is not None and delete_opts.destructive is True
    assert bucket_opts is not None and bucket_opts.destructive is True


# MARK: - Agent-ready summaries (Lambda)


def test_lambda_list_functions_summary() -> None:
    connector, transport = _lambda()
    transport.enqueue(
        json_response(
            {
                "Functions": [
                    {
                        "FunctionName": "myfn",
                        "FunctionArn": "arn:aws:lambda:us-east-1:1:function:myfn",
                        "Runtime": "python3.12",
                        "MemorySize": 256,
                        "Timeout": 30,
                        "LastModified": "2026-05-16T00:00:00.000+0000",
                        "Handler": "app.handler",
                    },
                ],
                "NextMarker": "marker-2",
            }
        )
    )
    result = connector.list_functions()
    assert result["functions"][0]["function_ref"] == "function_1"
    assert result["functions"][0]["name"] == "myfn"
    assert result["functions"][0]["runtime"] == "python3.12"
    assert "function_arn" not in result["functions"][0]
    assert result["next_marker"] == "marker-2"


def test_lambda_list_functions_include_ids() -> None:
    connector, transport = _lambda()
    transport.enqueue(
        json_response(
            {
                "Functions": [
                    {
                        "FunctionName": "myfn",
                        "FunctionArn": "arn:aws:lambda:us-east-1:1:function:myfn",
                    }
                ]
            }
        )
    )
    result = connector.list_functions(include_ids=True)
    assert result["functions"][0]["function_arn"].startswith("arn:aws:lambda:")


def test_lambda_delete_function_marked_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _lambda()
    opts = get_toolify_options(connector.delete_function)
    assert opts is not None and opts.destructive is True


def test_lambda_delete_function_accepts_dict() -> None:
    connector, transport = _lambda()
    transport.enqueue(json_response({"deleted": True}))
    connector.delete_function({"FunctionName": "myfn"})
    assert transport.requests[0].method == "DELETE"
    assert "/functions/myfn" in transport.requests[0].url


# MARK: - Agent-ready summaries (CloudWatch Logs)


def test_cwl_describe_log_groups_summary() -> None:
    connector, transport = _cwl()
    transport.enqueue(
        json_response(
            {
                "logGroups": [
                    {
                        "logGroupName": "/aws/lambda/myfn",
                        "retentionInDays": 14,
                        "storedBytes": 1024,
                        "creationTime": 1234,
                        "metricFilterCount": 0,
                        "arn": "arn:aws:logs:us-east-1:1:log-group:/aws/lambda/myfn",
                    }
                ],
                "nextToken": "ntoken",
            }
        )
    )
    result = connector.describe_log_groups()
    assert result["log_groups"][0]["log_group_ref"] == "log_group_1"
    assert result["log_groups"][0]["name"] == "/aws/lambda/myfn"
    assert result["log_groups"][0]["retention_in_days"] == 14
    assert result["next_token"] == "ntoken"


def test_cwl_describe_log_streams_summary() -> None:
    connector, transport = _cwl()
    transport.enqueue(
        json_response(
            {
                "logStreams": [
                    {
                        "logStreamName": "2026/05/16/[$LATEST]abc",
                        "firstEventTimestamp": 100,
                        "lastEventTimestamp": 200,
                        "storedBytes": 512,
                    }
                ]
            }
        )
    )
    result = connector.describe_log_streams(log_group_name="/aws/lambda/myfn")
    assert result["log_streams"][0]["log_stream_ref"] == "log_stream_1"
    assert result["log_streams"][0]["name"].startswith("2026/05/16")


def test_cwl_delete_log_group_marked_destructive() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _cwl()
    opts = get_toolify_options(connector.delete_log_group)
    assert opts is not None and opts.destructive is True


def test_cwl_delete_log_group_accepts_dict() -> None:
    connector, transport = _cwl()
    transport.enqueue(json_response({}))
    connector.delete_log_group(log_group_name={"logGroupName": "/aws/lambda/myfn"})
    assert transport.requests[0].method == "POST"
    body = transport.requests[0].json_body
    assert body == {"logGroupName": "/aws/lambda/myfn"}


# MARK: - Agent-ready summaries (IAM)


_NS = 'xmlns="https://iam.amazonaws.com/doc/2010-05-08/"'


def test_iam_list_users_summary() -> None:
    connector, transport = _iam()
    transport.enqueue(
        text_response(
            f"""<ListUsersResponse {_NS}>
              <ListUsersResult>
                <Users>
                  <member>
                    <UserName>alice</UserName>
                    <UserId>AIDA</UserId>
                    <Path>/</Path>
                    <Arn>arn:aws:iam::1:user/alice</Arn>
                    <CreateDate>2026-01-01T00:00:00Z</CreateDate>
                    <PasswordLastUsed>2026-05-15T00:00:00Z</PasswordLastUsed>
                  </member>
                </Users>
              </ListUsersResult>
            </ListUsersResponse>"""
        )
    )
    result = connector.list_users()
    assert result["users"][0]["user_ref"] == "user_1"
    assert result["users"][0]["user_name"] == "alice"
    assert "user_id" not in result["users"][0]
    assert "arn" not in result["users"][0]


def test_iam_list_users_include_ids() -> None:
    connector, transport = _iam()
    transport.enqueue(
        text_response(
            f"""<ListUsersResponse {_NS}>
              <ListUsersResult>
                <Users>
                  <member>
                    <UserName>alice</UserName>
                    <UserId>AIDA</UserId>
                    <Arn>arn:aws:iam::1:user/alice</Arn>
                  </member>
                </Users>
              </ListUsersResult>
            </ListUsersResponse>"""
        )
    )
    result = connector.list_users(include_ids=True)
    assert result["users"][0]["user_id"] == "AIDA"
    assert result["users"][0]["arn"].startswith("arn:aws:iam::")


def test_iam_list_roles_summary() -> None:
    connector, transport = _iam()
    transport.enqueue(
        text_response(
            f"""<ListRolesResponse {_NS}>
              <ListRolesResult>
                <Roles>
                  <member>
                    <RoleName>MyRole</RoleName>
                    <RoleId>AROA</RoleId>
                    <Path>/</Path>
                    <Arn>arn:aws:iam::1:role/MyRole</Arn>
                    <Description>for lambda</Description>
                    <CreateDate>2026-01-01T00:00:00Z</CreateDate>
                    <MaxSessionDuration>3600</MaxSessionDuration>
                  </member>
                </Roles>
              </ListRolesResult>
            </ListRolesResponse>"""
        )
    )
    result = connector.list_roles()
    assert result["roles"][0]["role_ref"] == "role_1"
    assert result["roles"][0]["role_name"] == "MyRole"
    assert "role_id" not in result["roles"][0]


def test_iam_list_policies_summary() -> None:
    connector, transport = _iam()
    transport.enqueue(
        text_response(
            f"""<ListPoliciesResponse {_NS}>
              <ListPoliciesResult>
                <Policies>
                  <member>
                    <PolicyName>MyPolicy</PolicyName>
                    <Arn>arn:aws:iam::1:policy/MyPolicy</Arn>
                    <PolicyId>ANPA</PolicyId>
                    <Path>/</Path>
                    <AttachmentCount>2</AttachmentCount>
                    <Description>an example</Description>
                    <CreateDate>2026-01-01T00:00:00Z</CreateDate>
                    <IsAttachable>true</IsAttachable>
                  </member>
                </Policies>
              </ListPoliciesResult>
            </ListPoliciesResponse>"""
        )
    )
    result = connector.list_policies()
    assert result["policies"][0]["policy_ref"] == "policy_1"
    assert result["policies"][0]["policy_name"] == "MyPolicy"
    assert result["policies"][0]["attachment_count"] == "2"
    assert "policy_arn" not in result["policies"][0]

    transport.enqueue(
        text_response(
            f"""<ListPoliciesResponse {_NS}>
              <ListPoliciesResult>
                <Policies>
                  <member>
                    <PolicyName>MyPolicy</PolicyName>
                    <Arn>arn:aws:iam::1:policy/MyPolicy</Arn>
                    <PolicyId>ANPA</PolicyId>
                  </member>
                </Policies>
              </ListPoliciesResult>
            </ListPoliciesResponse>"""
        )
    )
    result = connector.list_policies(include_ids=True)
    assert result["policies"][0]["policy_arn"].startswith("arn:aws:iam::")


def test_iam_destructive_tools_marked() -> None:
    from maivn._internal.utils.toolset import get_toolify_options

    connector, _ = _iam()
    delete_user_opts = get_toolify_options(connector.delete_user)
    delete_role_opts = get_toolify_options(connector.delete_role)
    detach_opts = get_toolify_options(connector.detach_user_policy)
    delete_key_opts = get_toolify_options(connector.delete_access_key)
    assert delete_user_opts is not None and delete_user_opts.destructive is True
    assert delete_role_opts is not None and delete_role_opts.destructive is True
    assert detach_opts is not None and detach_opts.destructive is True
    assert delete_key_opts is not None and delete_key_opts.destructive is True


def test_iam_delete_user_accepts_dict() -> None:
    connector, transport = _iam()
    transport.enqueue(json_response({}))
    connector.delete_user({"UserName": "bob"})
    body = transport.requests[0].data
    assert b"UserName=bob" in (body or b"")
    assert b"Action=DeleteUser" in (body or b"")


def test_iam_attach_user_policy_accepts_dicts() -> None:
    connector, transport = _iam()
    transport.enqueue(json_response({}))
    connector.attach_user_policy(
        user_name={"UserName": "bob"},
        policy_arn={"Arn": "arn:aws:iam::1:policy/p"},
    )
    body = transport.requests[0].data or b""
    assert b"UserName=bob" in body
    assert b"PolicyArn=arn" in body
