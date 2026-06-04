# pyright: strict
from __future__ import annotations

from collections.abc import Callable

import pytest

from maivn_tools.connectors.aws_ses import AmazonSESToolSet
from maivn_tools.connectors.brevo import BrevoToolSet
from maivn_tools.connectors.customerio import CustomerIOToolSet
from maivn_tools.connectors.klaviyo import KlaviyoToolSet
from maivn_tools.connectors.loops import LoopsToolSet
from maivn_tools.connectors.mailchimp import MailchimpToolSet
from maivn_tools.connectors.mailgun import MailgunToolSet
from maivn_tools.connectors.mandrill import MandrillToolSet
from maivn_tools.connectors.postmark import PostmarkToolSet
from maivn_tools.connectors.resend import ResendToolSet
from maivn_tools.connectors.sendgrid import SendGridToolSet
from maivn_tools.testing import MockTransport, json_response


def _is_destructive(method: Callable[..., object]) -> bool:
    from maivn._internal.utils.toolset import get_toolify_options

    opts = get_toolify_options(method)
    return bool(opts and opts.destructive)


# MARK: - Resend


def test_resend() -> None:
    transport = MockTransport()
    connector = ResendToolSet(api_key="re_xxx", transport=transport)
    for _ in range(14):
        transport.enqueue(json_response({"id": "x"}))
    connector.send_email(
        from_address="x@y",
        to=["a@b"],
        subject="Hi",
        html="<p>Hi</p>",
        cc=["c@d"],
        bcc=["e@f"],
        reply_to=["r@s"],
        tags=[{"name": "k", "value": "v"}],
        scheduled_at="2026-06-01T00:00:00Z",
    )
    connector.send_batch([{"from": "x", "to": ["a"], "subject": "s", "html": "h"}])
    connector.get_email("e1")
    connector.cancel_email("e1")
    connector.list_domains()
    connector.create_domain(name="example.com", region="us-east-1")
    connector.verify_domain("d1")
    connector.delete_domain("d1")
    connector.list_audiences()
    connector.create_audience(name="aud")
    connector.create_contact("aud", email="x@y", first_name="A", unsubscribed=False)
    connector.list_contacts("aud")
    connector.delete_contact("aud", "c1")
    connector.create_broadcast(
        audience_id="aud",
        from_address="x@y",
        subject="s",
        html="h",
        name="b",
    )
    assert transport.requests[0].headers["Authorization"] == "Bearer re_xxx"
    assert transport.requests[0].json_body["tags"]
    with pytest.raises(ValueError):
        ResendToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.send_email(from_address="", to=["a"], subject="x", text="t")
    with pytest.raises(ValueError):
        connector.send_email(from_address="x", to=["a"], subject="x")
    with pytest.raises(ValueError):
        connector.send_batch([])
    with pytest.raises(ValueError):
        connector.get_email("")
    with pytest.raises(ValueError):
        connector.create_domain(name="")
    with pytest.raises(ValueError):
        connector.create_contact("", email="x@y")
    with pytest.raises(ValueError):
        connector.delete_contact("", "")
    with pytest.raises(ValueError):
        connector.create_broadcast(audience_id="", from_address="x", subject="s", html="h")
    with pytest.raises(ValueError):
        connector.create_broadcast(audience_id="a", from_address="x", subject="s")


def test_resend_more() -> None:
    transport = MockTransport()
    connector = ResendToolSet(api_key="re_xxx", transport=transport)
    transport.enqueue(json_response({"broadcasts": []}))
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({"data": []}))
    connector.list_broadcasts()
    connector.send_broadcast("b1")
    connector.list_api_keys()
    with pytest.raises(ValueError):
        connector.send_broadcast("")


def test_resend_send_email_destructive() -> None:
    assert _is_destructive(ResendToolSet.send_email)
    assert _is_destructive(ResendToolSet.send_batch)
    assert _is_destructive(ResendToolSet.cancel_email)
    assert _is_destructive(ResendToolSet.delete_domain)
    assert _is_destructive(ResendToolSet.delete_contact)
    assert _is_destructive(ResendToolSet.send_broadcast)


def test_resend_list_contacts_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = ResendToolSet(api_key="re_xxx", transport=transport)
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "c_999",
                        "email": "alice@x",
                        "first_name": "Alice",
                        "last_name": "Example",
                        "unsubscribed": False,
                    }
                ]
            }
        )
    )
    result = connector.list_contacts("aud")
    contact = result["contacts"][0]
    assert contact["contact_ref"] == "contact_1"
    assert contact["name"] == "Alice Example"
    assert contact["email"] == "alice@x"
    assert "contact_id" not in contact


def test_resend_list_contacts_include_ids() -> None:
    transport = MockTransport()
    connector = ResendToolSet(api_key="re_xxx", transport=transport)
    transport.enqueue(json_response({"data": [{"id": "c_777", "email": "x@y"}]}))
    result = connector.list_contacts("aud", include_ids=True)
    assert result["contacts"][0]["contact_id"] == "c_777"


# MARK: - SendGrid


def test_sendgrid() -> None:
    transport = MockTransport()
    connector = SendGridToolSet(api_key="sg_xxx", transport=transport)
    for _ in range(12):
        transport.enqueue(json_response({}))
    connector.send_email(
        from_address="x@y",
        to=["a@b"],
        subject="Hi",
        text="t",
        html="<p>Hi</p>",
        template_id="tpl-1",
        dynamic_template_data={"name": "A"},
        cc=["c@d"],
        bcc=["e@f"],
        categories=["promo"],
        send_at=1234567,
    )
    connector.list_templates()
    connector.get_template("tpl-1")
    connector.create_template(name="My Tpl")
    connector.delete_template("tpl-1")
    connector.get_marketing_contacts()
    connector.upsert_marketing_contacts([{"email": "x@y"}], list_ids=["L1"])
    connector.list_lists()
    connector.create_list(name="L1")
    connector.delete_list("L1", delete_contacts=True)
    connector.list_bounces(start_time=100, end_time=200)
    connector.list_blocks()
    body = transport.requests[0].json_body
    assert body["personalizations"][0]["dynamic_template_data"] == {"name": "A"}
    with pytest.raises(ValueError):
        SendGridToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.send_email(from_address="", to=[], subject="x")
    with pytest.raises(ValueError):
        connector.get_template("")
    with pytest.raises(ValueError):
        connector.create_template(name="")
    with pytest.raises(ValueError):
        connector.delete_template("")
    with pytest.raises(ValueError):
        connector.upsert_marketing_contacts([])
    with pytest.raises(ValueError):
        connector.create_list(name="")
    with pytest.raises(ValueError):
        connector.delete_list("")
    with pytest.raises(ValueError):
        connector.delete_bounce("")


def test_sendgrid_extra_endpoints() -> None:
    transport = MockTransport()
    connector = SendGridToolSet(api_key="sg_xxx", transport=transport)
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.delete_bounce("x@y")
    connector.get_account_scopes()
    assert transport.requests[0].method == "DELETE"


def test_sendgrid_destructive_tagging() -> None:
    assert _is_destructive(SendGridToolSet.send_email)
    assert _is_destructive(SendGridToolSet.delete_template)
    assert _is_destructive(SendGridToolSet.delete_list)
    assert _is_destructive(SendGridToolSet.delete_bounce)


def test_sendgrid_list_lists_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = SendGridToolSet(api_key="sg_xxx", transport=transport)
    transport.enqueue(
        json_response(
            {
                "result": [
                    {
                        "id": "list-uuid-999",
                        "name": "Promo",
                        "contact_count": 42,
                    }
                ]
            }
        )
    )
    result = connector.list_lists()
    lst = result["lists"][0]
    assert lst["list_ref"] == "list_1"
    assert lst["name"] == "Promo"
    assert lst["contact_count"] == 42
    assert "list_id" not in lst


def test_sendgrid_list_lists_include_ids() -> None:
    transport = MockTransport()
    connector = SendGridToolSet(api_key="sg_xxx", transport=transport)
    transport.enqueue(json_response({"result": [{"id": "L1", "name": "X"}]}))
    result = connector.list_lists(include_ids=True)
    assert result["lists"][0]["list_id"] == "L1"


def test_sendgrid_list_templates_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = SendGridToolSet(api_key="sg_xxx", transport=transport)
    transport.enqueue(
        json_response(
            {
                "result": [
                    {
                        "id": "tpl-uuid-1",
                        "name": "Welcome",
                        "generation": "dynamic",
                        "updated_at": "2026-01-01",
                    }
                ]
            }
        )
    )
    result = connector.list_templates()
    tpl = result["templates"][0]
    assert tpl["template_ref"] == "template_1"
    assert tpl["name"] == "Welcome"
    assert "template_id" not in tpl


# MARK: - Mailgun


def test_mailgun() -> None:
    transport = MockTransport()
    connector = MailgunToolSet(api_key="key-xxx", domain="example.com", transport=transport)
    for _ in range(10):
        transport.enqueue(json_response({}))
    connector.send_email(
        from_address="x@y",
        to=["a@b"],
        subject="Hi",
        text="t",
        html="<p>h</p>",
        cc=["c@d"],
        bcc=["e@f"],
        tag=["promo"],
        template="my_t",
        template_variables={"name": "A"},
        delivery_time="Mon, 1 Jun 2026 00:00 UTC",
    )
    connector.list_domains()
    connector.create_domain(name="x.com", wildcard=True)
    connector.delete_domain("x.com")
    connector.list_events(event="delivered", begin="x", end="y")
    connector.list_bounces()
    connector.delete_bounce("a@b")
    connector.list_mailing_lists()
    connector.create_mailing_list(address="list@x.com", name="L", description="d")
    connector.add_list_member("list@x.com", address="a@b", name="A")
    assert transport.requests[0].headers["Authorization"].startswith("Basic ")
    assert transport.requests[0].params["to"] == ["a@b"]
    with pytest.raises(ValueError):
        MailgunToolSet(api_key="")
    with pytest.raises(ValueError):
        MailgunToolSet(api_key="x").send_email(from_address="a", to=["b"], subject="s", text="t")
    with pytest.raises(ValueError):
        connector.send_email(from_address="", to=["a"], subject="s", text="t")
    with pytest.raises(ValueError):
        connector.send_email(from_address="x", to=["a"], subject="s")
    with pytest.raises(ValueError):
        connector.create_domain(name="")
    with pytest.raises(ValueError):
        connector.delete_domain("")
    with pytest.raises(ValueError):
        connector.delete_bounce("")
    with pytest.raises(ValueError):
        connector.create_mailing_list(address="")
    with pytest.raises(ValueError):
        connector.add_list_member("", address="a@b")


def test_mailgun_destructive_tagging() -> None:
    assert _is_destructive(MailgunToolSet.send_email)
    assert _is_destructive(MailgunToolSet.delete_domain)
    assert _is_destructive(MailgunToolSet.delete_bounce)


def test_mailgun_list_domains_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = MailgunToolSet(api_key="k", domain="x.com", transport=transport)
    transport.enqueue(
        json_response(
            {
                "items": [
                    {
                        "id": "dom_999",
                        "name": "example.com",
                        "state": "active",
                        "type": "custom",
                    }
                ],
                "total_count": 1,
            }
        )
    )
    result = connector.list_domains()
    domain = result["domains"][0]
    assert domain["domain_ref"] == "domain_1"
    assert domain["name"] == "example.com"
    assert "id" not in domain


def test_mailgun_list_domains_include_ids() -> None:
    transport = MockTransport()
    connector = MailgunToolSet(api_key="k", domain="x.com", transport=transport)
    transport.enqueue(json_response({"items": [{"id": "d_42", "name": "x.com"}]}))
    result = connector.list_domains(include_ids=True)
    assert result["domains"][0]["id"] == "d_42"


# MARK: - Postmark


def test_postmark() -> None:
    transport = MockTransport()
    connector = PostmarkToolSet(server_token="srv_xxx", transport=transport)
    for _ in range(10):
        transport.enqueue(json_response({}))
    connector.send_email(
        from_address="x@y",
        to=["a@b"],
        subject="Hi",
        text_body="t",
        html_body="<p>h</p>",
        cc="c@d",
        bcc="e@f",
        track_opens=True,
        message_stream="outbound",
    )
    connector.send_email(
        from_address="x@y",
        to="a@b",
        subject=None,
        template_id=1,
        template_model={"name": "A"},
    )
    connector.send_batch([{"From": "x", "To": "y"}])
    connector.list_templates(template_type="Standard")
    connector.get_template("tpl-1")
    connector.create_template(name="My", subject="S", html_body="<p>h</p>", alias="my")
    connector.delete_template("my")
    connector.list_outbound_messages(recipient="r@x")
    connector.get_outbound_message("m1")
    connector.list_message_streams()
    assert transport.requests[0].headers["X-Postmark-Server-Token"] == "srv_xxx"
    assert transport.requests[1].url.endswith("/email/withTemplate")
    with pytest.raises(ValueError):
        PostmarkToolSet()
    with pytest.raises(ValueError):
        connector.send_email(from_address="", to=["x@y"])
    with pytest.raises(ValueError):
        connector.send_batch([])
    with pytest.raises(ValueError):
        connector.create_template(name="", subject="s")
    with pytest.raises(ValueError):
        connector.get_outbound_message("")


def test_postmark_account_endpoints() -> None:
    transport = MockTransport()
    connector = PostmarkToolSet(account_token="act_xxx", transport=transport)
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.list_servers()
    connector.get_delivery_stats()
    assert transport.requests[0].headers["X-Postmark-Account-Token"] == "act_xxx"


def test_postmark_destructive_tagging() -> None:
    assert _is_destructive(PostmarkToolSet.send_email)
    assert _is_destructive(PostmarkToolSet.send_batch)
    assert _is_destructive(PostmarkToolSet.delete_template)


def test_postmark_list_templates_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = PostmarkToolSet(server_token="srv", transport=transport)
    transport.enqueue(
        json_response(
            {
                "Templates": [
                    {
                        "TemplateId": 7777,
                        "Name": "Welcome",
                        "Alias": "welcome",
                        "TemplateType": "Standard",
                        "Active": True,
                    }
                ],
                "TotalCount": 1,
            }
        )
    )
    result = connector.list_templates()
    tpl = result["templates"][0]
    assert tpl["template_ref"] == "template_1"
    assert tpl["alias"] == "welcome"
    assert "template_id" not in tpl


def test_postmark_list_outbound_messages_returns_summaries() -> None:
    transport = MockTransport()
    connector = PostmarkToolSet(server_token="srv", transport=transport)
    transport.enqueue(
        json_response(
            {
                "Messages": [
                    {
                        "MessageID": "msg-uuid-1",
                        "From": "x@y",
                        "Recipients": ["a@b"],
                        "Subject": "Hello",
                        "Status": "Sent",
                    }
                ],
                "TotalCount": 1,
            }
        )
    )
    result = connector.list_outbound_messages()
    msg = result["messages"][0]
    assert msg["message_ref"] == "message_1"
    assert msg["from_address"] == "x@y"
    assert "message_id" not in msg


def test_postmark_list_outbound_messages_include_ids() -> None:
    transport = MockTransport()
    connector = PostmarkToolSet(server_token="srv", transport=transport)
    transport.enqueue(
        json_response(
            {"Messages": [{"MessageID": "uuid-99", "From": "x", "Recipients": [], "Subject": ""}]}
        )
    )
    result = connector.list_outbound_messages(include_ids=True)
    assert result["messages"][0]["message_id"] == "uuid-99"


# MARK: - AWS SES


def test_aws_ses() -> None:
    transport = MockTransport()
    connector = AmazonSESToolSet(region="us-east-1", transport=transport)
    for _ in range(11):
        transport.enqueue(json_response({}))
    connector.send_email(
        from_address="x@y",
        to=["a@b"],
        subject="Hi",
        text_body="t",
        html_body="<p>h</p>",
        cc=["c@d"],
        bcc=["e@f"],
        configuration_set_name="default",
        tags=[{"Name": "k", "Value": "v"}],
    )
    connector.send_template(
        from_address="x@y",
        to=["a@b"],
        template_name="MyT",
        template_data={"name": "A"},
        configuration_set_name="default",
    )
    connector.list_identities()
    connector.get_identity("x@y")
    connector.create_identity("x@y")
    connector.delete_identity("x@y")
    connector.list_templates()
    connector.create_template(
        name="My",
        subject_part="Hi {{name}}",
        text_part="hi",
        html_part="<p>hi</p>",
    )
    connector.delete_template("My")
    connector.list_suppressed_destinations(reasons=["BOUNCE", "COMPLAINT"])
    connector.remove_suppressed_destination("x@y")
    body = transport.requests[0].json_body
    assert body["FromEmailAddress"] == "x@y"
    assert body["Destination"]["ToAddresses"] == ["a@b"]
    with pytest.raises(ValueError):
        AmazonSESToolSet(region="")
    with pytest.raises(ValueError):
        connector.send_email(from_address="", to=["a"], subject="s", text_body="t")
    with pytest.raises(ValueError):
        connector.send_email(from_address="x", to=["a"], subject="s")
    with pytest.raises(ValueError):
        connector.send_template(from_address="x", to=["a"], template_name="", template_data={})
    with pytest.raises(ValueError):
        connector.get_identity("")
    with pytest.raises(ValueError):
        connector.create_identity("")
    with pytest.raises(ValueError):
        connector.delete_identity("")
    with pytest.raises(ValueError):
        connector.create_template(name="", subject_part="s")
    with pytest.raises(ValueError):
        connector.delete_template("")
    with pytest.raises(ValueError):
        connector.remove_suppressed_destination("")


def test_aws_ses_destructive_tagging() -> None:
    assert _is_destructive(AmazonSESToolSet.send_email)
    assert _is_destructive(AmazonSESToolSet.send_template)
    assert _is_destructive(AmazonSESToolSet.delete_identity)
    assert _is_destructive(AmazonSESToolSet.delete_template)
    assert _is_destructive(AmazonSESToolSet.remove_suppressed_destination)


def test_aws_ses_list_identities_returns_summaries_without_arn() -> None:
    transport = MockTransport()
    connector = AmazonSESToolSet(region="us-east-1", transport=transport)
    transport.enqueue(
        json_response(
            {
                "EmailIdentities": [
                    {
                        "IdentityName": "marketing@example.com",
                        "IdentityType": "EMAIL_ADDRESS",
                        "SendingEnabled": True,
                        "VerificationStatus": "SUCCESS",
                        "IdentityArn": "arn:aws:ses:us-east-1:000:identity/x",
                    }
                ]
            }
        )
    )
    result = connector.list_identities()
    ident = result["identities"][0]
    assert ident["identity_ref"] == "identity_1"
    assert ident["identity_name"] == "marketing@example.com"
    assert "identity_arn" not in ident


def test_aws_ses_list_identities_include_ids() -> None:
    transport = MockTransport()
    connector = AmazonSESToolSet(region="us-east-1", transport=transport)
    transport.enqueue(
        json_response(
            {
                "EmailIdentities": [
                    {"IdentityName": "x", "IdentityArn": "arn:aws:ses:us-east-1:000:identity/x"}
                ]
            }
        )
    )
    result = connector.list_identities(include_ids=True)
    assert result["identities"][0]["identity_arn"] == "arn:aws:ses:us-east-1:000:identity/x"


# MARK: - Brevo


def test_brevo() -> None:
    transport = MockTransport()
    connector = BrevoToolSet(api_key="api-xxx", transport=transport)
    for _ in range(11):
        transport.enqueue(json_response({}))
    connector.send_transactional_email(
        sender={"email": "x@y", "name": "X"},
        to=[{"email": "a@b"}],
        subject="Hi",
        html_content="<p>h</p>",
        text_content="t",
        template_id=1,
        params={"name": "A"},
        attachments=[{"name": "a.pdf", "content": "..."}],
        reply_to={"email": "r@s"},
        tags=["promo"],
        scheduled_at="2026-06-01T00:00:00Z",
    )
    connector.list_contacts()
    connector.get_contact("a@b")
    connector.create_contact(email="a@b", attributes={"FIRSTNAME": "A"}, list_ids=[1])
    connector.update_contact("a@b", {"attributes": {"LASTNAME": "B"}})
    connector.delete_contact("a@b")
    connector.list_lists()
    connector.create_list(name="L", folder_id=1)
    connector.list_email_campaigns(type="classic", status="sent")
    connector.send_sms(sender="MyApp", recipient="+15551234567", content="Hi")
    connector.get_account()
    assert transport.requests[0].headers["api-key"] == "api-xxx"
    with pytest.raises(ValueError):
        BrevoToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.send_transactional_email(sender={}, to=[{"email": "x"}])
    with pytest.raises(ValueError):
        connector.get_contact("")
    with pytest.raises(ValueError):
        connector.create_contact(email="")
    with pytest.raises(ValueError):
        connector.update_contact("", {"x": 1})
    with pytest.raises(ValueError):
        connector.delete_contact("")
    with pytest.raises(ValueError):
        connector.create_list(name="", folder_id=1)
    with pytest.raises(ValueError):
        connector.send_sms(sender="", recipient="r", content="c")
    with pytest.raises(ValueError):
        connector.send_sms(sender="s", recipient="r", content="c", type="bogus")


def test_brevo_destructive_tagging() -> None:
    assert _is_destructive(BrevoToolSet.send_transactional_email)
    assert _is_destructive(BrevoToolSet.send_sms)
    assert _is_destructive(BrevoToolSet.delete_contact)


def test_brevo_list_contacts_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = BrevoToolSet(api_key="k", transport=transport)
    transport.enqueue(
        json_response(
            {
                "contacts": [
                    {
                        "id": 555,
                        "email": "alice@x",
                        "emailBlacklisted": False,
                        "smsBlacklisted": False,
                        "attributes": {"FIRSTNAME": "Alice", "LASTNAME": "Example"},
                    }
                ],
                "count": 1,
            }
        )
    )
    result = connector.list_contacts()
    contact = result["contacts"][0]
    assert contact["contact_ref"] == "contact_1"
    assert contact["name"] == "Alice Example"
    assert contact["email"] == "alice@x"
    assert "contact_id" not in contact


def test_brevo_list_contacts_include_ids() -> None:
    transport = MockTransport()
    connector = BrevoToolSet(api_key="k", transport=transport)
    transport.enqueue(json_response({"contacts": [{"id": 99, "email": "x"}]}))
    result = connector.list_contacts(include_ids=True)
    assert result["contacts"][0]["contact_id"] == 99


# MARK: - Mandrill


def test_mandrill() -> None:
    transport = MockTransport()
    connector = MandrillToolSet(api_key="md_xxx", transport=transport)
    for _ in range(10):
        transport.enqueue(json_response({}))
    connector.ping()
    connector.get_user_info()
    connector.send_email(
        from_email="x@y",
        to=[{"email": "a@b"}],
        subject="Hi",
        html="<p>h</p>",
        from_name="X",
        attachments=[{"name": "a.pdf", "content": "..."}],
        merge_vars=[{"rcpt": "a@b", "vars": [{"name": "x", "content": "y"}]}],
        tags=["promo"],
        async_send=True,
        send_at="2026-06-01T00:00:00Z",
    )
    connector.send_template(
        template_name="my",
        template_content=[{"name": "x", "content": "y"}],
        message={"to": [{"email": "a@b"}]},
        async_send=True,
    )
    connector.get_message_info("m1")
    connector.list_templates()
    connector.add_template(name="my", subject="s", code="<html/>", publish=False)
    connector.delete_template(name="my")
    connector.list_webhooks()
    connector.add_webhook(url="https://x/h", events=["send", "open"], description="d")
    assert transport.requests[2].json_body["key"] == "md_xxx"
    with pytest.raises(ValueError):
        MandrillToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.send_email(from_email="", to=[{"email": "a"}], subject="s", text="t")
    with pytest.raises(ValueError):
        connector.send_email(from_email="x", to=[{"email": "a"}], subject="s")
    with pytest.raises(ValueError):
        connector.send_template(template_name="", template_content=[], message={})
    with pytest.raises(ValueError):
        connector.get_message_info("")
    with pytest.raises(ValueError):
        connector.add_template(name="")
    with pytest.raises(ValueError):
        connector.delete_template(name="")
    with pytest.raises(ValueError):
        connector.add_webhook(url="", events=["send"])


def test_mandrill_destructive_tagging() -> None:
    assert _is_destructive(MandrillToolSet.send_email)
    assert _is_destructive(MandrillToolSet.send_template)
    assert _is_destructive(MandrillToolSet.delete_template)


def test_mandrill_list_templates_returns_summaries() -> None:
    transport = MockTransport()
    connector = MandrillToolSet(api_key="md_xxx", transport=transport)
    transport.enqueue(
        json_response(
            [
                {
                    "slug": "welcome",
                    "name": "Welcome Email",
                    "subject": "Welcome!",
                    "from_email": "x@y",
                }
            ]
        )
    )
    result = connector.list_templates()
    tpl = result["templates"][0]
    assert tpl["template_ref"] == "template_1"
    assert tpl["slug"] == "welcome"
    assert tpl["name"] == "Welcome Email"


# MARK: - Customer.io


def test_customerio() -> None:
    transport = MockTransport()
    connector = CustomerIOToolSet(
        track_site_id="sid",
        track_api_key="tkey",
        app_api_key="app",
        transport=transport,
    )
    for _ in range(10):
        transport.enqueue(json_response({}))
    connector.identify("u1", {"email": "x@y"})
    connector.delete_customer("u1")
    connector.track_event("u1", name="purchase", data={"sku": "x"}, timestamp=123)
    connector.track_anonymous_event(name="visit", data={"page": "/"}, anonymous_id="a1")
    connector.send_transactional(
        transactional_message_id=1,
        to="x@y",
        identifiers={"id": "u1"},
        message_data={"name": "A"},
        from_address="from@x",
        subject="Hi",
        body="body",
    )
    connector.list_segments()
    connector.list_broadcasts()
    connector.trigger_broadcast(1, emails=["a@b"], data={"x": 1})
    connector.list_campaigns()
    connector.get_customer(email="x@y")
    assert transport.requests[0].method == "PUT"
    with pytest.raises(ValueError):
        CustomerIOToolSet(region="us")
    with pytest.raises(ValueError):
        CustomerIOToolSet(region="bogus", app_api_key="x")
    with pytest.raises(ValueError):
        connector.identify("", {"x": 1})
    with pytest.raises(ValueError):
        connector.delete_customer("")
    with pytest.raises(ValueError):
        connector.track_event("u1", name="")
    with pytest.raises(ValueError):
        connector.track_anonymous_event(name="")
    with pytest.raises(ValueError):
        connector.send_transactional(transactional_message_id=1, to="", identifiers={"id": "u1"})
    with pytest.raises(ValueError):
        connector.get_customer()


def test_customerio_track_only_blocks_app_calls() -> None:
    transport = MockTransport()
    connector = CustomerIOToolSet(
        track_site_id="sid",
        track_api_key="tkey",
        transport=transport,
    )
    with pytest.raises(RuntimeError):
        connector.list_segments()


def test_customerio_destructive_tagging() -> None:
    assert _is_destructive(CustomerIOToolSet.delete_customer)
    assert _is_destructive(CustomerIOToolSet.send_transactional)
    assert _is_destructive(CustomerIOToolSet.trigger_broadcast)


def test_customerio_list_segments_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = CustomerIOToolSet(app_api_key="app", transport=transport)
    transport.enqueue(
        json_response(
            {
                "segments": [
                    {
                        "id": 9999,
                        "name": "VIPs",
                        "description": "Top spenders",
                        "type": "manual",
                        "state": "active",
                    }
                ]
            }
        )
    )
    result = connector.list_segments()
    seg = result["segments"][0]
    assert seg["segment_ref"] == "segment_1"
    assert seg["name"] == "VIPs"
    assert "segment_id" not in seg


def test_customerio_list_segments_include_ids() -> None:
    transport = MockTransport()
    connector = CustomerIOToolSet(app_api_key="app", transport=transport)
    transport.enqueue(json_response({"segments": [{"id": 7, "name": "X"}]}))
    result = connector.list_segments(include_ids=True)
    assert result["segments"][0]["segment_id"] == 7


# MARK: - Loops


def test_loops() -> None:
    transport = MockTransport()
    connector = LoopsToolSet(api_key="lp_xxx", transport=transport)
    for _ in range(9):
        transport.enqueue(json_response({}))
    connector.api_key_info()
    connector.send_transactional(
        transactional_id="t1",
        email="x@y",
        data_variables={"name": "A"},
        attachments=[{"filename": "x.pdf", "contentType": "application/pdf", "data": "..."}],
    )
    connector.find_contact(email="x@y")
    connector.create_contact(
        email="x@y",
        first_name="A",
        last_name="B",
        user_group="vips",
        user_id="u1",
        attributes={"plan": "pro"},
        mailing_lists={"weekly": True},
    )
    connector.update_contact(email="x@y", fields={"firstName": "C"})
    connector.delete_contact(email="x@y")
    connector.list_mailing_lists()
    connector.send_event(
        email="x@y",
        event_name="signup",
        event_properties={"plan": "pro"},
        mailing_lists={"weekly": True},
    )
    connector.send_event(user_id="u1", event_name="event2")
    assert transport.requests[0].headers["Authorization"] == "Bearer lp_xxx"
    with pytest.raises(ValueError):
        LoopsToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.send_transactional(transactional_id="", email="x")
    with pytest.raises(ValueError):
        connector.find_contact()
    with pytest.raises(ValueError):
        connector.create_contact(email="")
    with pytest.raises(ValueError):
        connector.update_contact(email="x", fields={})
    with pytest.raises(ValueError):
        connector.delete_contact()
    with pytest.raises(ValueError):
        connector.send_event(event_name="x")
    with pytest.raises(ValueError):
        connector.send_event(email="x", event_name="")


def test_loops_destructive_tagging() -> None:
    assert _is_destructive(LoopsToolSet.send_transactional)
    assert _is_destructive(LoopsToolSet.delete_contact)


def test_loops_list_mailing_lists_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = LoopsToolSet(api_key="lp", transport=transport)
    transport.enqueue(
        json_response(
            [
                {
                    "id": "list_uuid_99",
                    "name": "Weekly",
                    "description": "Weekly digest",
                    "isPublic": True,
                }
            ]
        )
    )
    result = connector.list_mailing_lists()
    lst = result["lists"][0]
    assert lst["list_ref"] == "list_1"
    assert lst["name"] == "Weekly"
    assert "list_id" not in lst


# MARK: - Klaviyo


def test_klaviyo() -> None:
    transport = MockTransport()
    connector = KlaviyoToolSet(api_key="pk_xxx", transport=transport)
    for _ in range(11):
        transport.enqueue(json_response({}))
    connector.list_profiles(filter="equals(email,'x@y')", sort="-created", page_cursor="c1")
    connector.get_profile("p1")
    connector.create_profile(email="x@y", attributes={"first_name": "A"})
    connector.update_profile("p1", {"last_name": "B"})
    connector.list_lists()
    connector.create_list(name="L")
    connector.add_profiles_to_list("L1", ["p1", "p2"])
    connector.remove_profiles_from_list("L1", ["p1"])
    connector.track_event(metric_name="Placed Order", profile_email="x@y", value=99.0)
    connector.list_metrics()
    connector.list_campaigns(filter="any(messages.channel,['email'])")
    auth = transport.requests[0].headers["Authorization"]
    assert auth == "Klaviyo-API-Key pk_xxx"
    assert transport.requests[0].headers["revision"] == "2025-04-15"
    with pytest.raises(ValueError):
        KlaviyoToolSet(api_key="")
    with pytest.raises(ValueError):
        connector.get_profile("")
    with pytest.raises(ValueError):
        connector.create_profile()
    with pytest.raises(ValueError):
        connector.update_profile("", {"x": 1})
    with pytest.raises(ValueError):
        connector.create_list(name="")
    with pytest.raises(ValueError):
        connector.add_profiles_to_list("", [])
    with pytest.raises(ValueError):
        connector.remove_profiles_from_list("L", [])
    with pytest.raises(ValueError):
        connector.track_event(metric_name="", profile_email="x")
    with pytest.raises(ValueError):
        connector.track_event(metric_name="x")


def test_klaviyo_more() -> None:
    transport = MockTransport()
    connector = KlaviyoToolSet(api_key="pk_xxx", transport=transport)
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.get_campaign("c1")
    connector.list_flows()
    with pytest.raises(ValueError):
        connector.get_campaign("")


def test_klaviyo_destructive_tagging() -> None:
    assert _is_destructive(KlaviyoToolSet.remove_profiles_from_list)


def test_klaviyo_list_profiles_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = KlaviyoToolSet(api_key="pk_xxx", transport=transport)
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "p_uuid_999",
                        "type": "profile",
                        "attributes": {
                            "email": "alice@x",
                            "first_name": "Alice",
                            "last_name": "Example",
                            "phone_number": "+15555555555",
                        },
                    }
                ],
                "links": {"next": "https://x.klaviyo.com/api/profiles?page[cursor]=abc"},
            }
        )
    )
    result = connector.list_profiles()
    profile = result["profiles"][0]
    assert profile["profile_ref"] == "profile_1"
    assert profile["name"] == "Alice Example"
    assert profile["email"] == "alice@x"
    assert "profile_id" not in profile


def test_klaviyo_list_profiles_include_ids() -> None:
    transport = MockTransport()
    connector = KlaviyoToolSet(api_key="pk_xxx", transport=transport)
    transport.enqueue(
        json_response({"data": [{"id": "p_77", "type": "profile", "attributes": {"email": "x"}}]})
    )
    result = connector.list_profiles(include_ids=True)
    assert result["profiles"][0]["profile_id"] == "p_77"


# MARK: - Mailchimp Marketing


def test_mailchimp() -> None:
    transport = MockTransport()
    connector = MailchimpToolSet(api_key="abc-us1", transport=transport)
    for _ in range(12):
        transport.enqueue(json_response({}))
    connector.ping()
    connector.list_lists()
    connector.get_list("L1")
    connector.list_members("L1", status="subscribed")
    connector.upsert_member("L1", email="x@y", merge_fields={"FNAME": "A"}, tags=["promo"])
    connector.archive_member("L1", email="x@y")
    connector.list_campaigns(status="sent")
    connector.create_campaign({"type": "regular", "recipients": {"list_id": "L1"}})
    connector.send_campaign("c1")
    connector.schedule_campaign("c1", schedule_time="2026-06-01T00:00:00Z")
    connector.delete_campaign("c1")
    connector.list_templates()
    assert "us1.api.mailchimp.com" in transport.requests[0].url
    assert transport.requests[0].headers["Authorization"].startswith("Basic ")
    with pytest.raises(ValueError):
        MailchimpToolSet(api_key="")
    with pytest.raises(ValueError):
        MailchimpToolSet(api_key="abc")
    with pytest.raises(ValueError):
        connector.get_list("")
    with pytest.raises(ValueError):
        connector.list_members("")
    with pytest.raises(ValueError):
        connector.upsert_member("", email="x")
    with pytest.raises(ValueError):
        connector.archive_member("L", email="")
    with pytest.raises(ValueError):
        connector.create_campaign({})
    with pytest.raises(ValueError):
        connector.send_campaign("")
    with pytest.raises(ValueError):
        connector.schedule_campaign("", schedule_time="x")
    with pytest.raises(ValueError):
        connector.delete_campaign("")


def test_mailchimp_reports() -> None:
    transport = MockTransport()
    connector = MailchimpToolSet(api_key="abc-us1", transport=transport)
    transport.enqueue(json_response({}))
    transport.enqueue(json_response({}))
    connector.list_reports()
    connector.get_report("c1")
    with pytest.raises(ValueError):
        connector.get_report("")


def test_mailchimp_destructive_tagging() -> None:
    assert _is_destructive(MailchimpToolSet.archive_member)
    assert _is_destructive(MailchimpToolSet.send_campaign)
    assert _is_destructive(MailchimpToolSet.delete_campaign)


def test_mailchimp_list_lists_returns_summaries_without_ids() -> None:
    transport = MockTransport()
    connector = MailchimpToolSet(api_key="abc-us1", transport=transport)
    transport.enqueue(
        json_response(
            {
                "lists": [
                    {
                        "id": "L_uuid_999",
                        "name": "Newsletter",
                        "stats": {"member_count": 1234, "unsubscribe_count": 12},
                        "date_created": "2026-01-01",
                    }
                ],
                "total_items": 1,
            }
        )
    )
    result = connector.list_lists()
    lst = result["lists"][0]
    assert lst["list_ref"] == "list_1"
    assert lst["name"] == "Newsletter"
    assert lst["member_count"] == 1234
    assert "list_id" not in lst


def test_mailchimp_list_lists_include_ids() -> None:
    transport = MockTransport()
    connector = MailchimpToolSet(api_key="abc-us1", transport=transport)
    transport.enqueue(json_response({"lists": [{"id": "L_42", "name": "X", "stats": {}}]}))
    result = connector.list_lists(include_ids=True)
    assert result["lists"][0]["list_id"] == "L_42"


def test_mailchimp_list_members_returns_subscribers() -> None:
    transport = MockTransport()
    connector = MailchimpToolSet(api_key="abc-us1", transport=transport)
    transport.enqueue(
        json_response(
            {
                "members": [
                    {
                        "id": "abc123",
                        "email_address": "alice@x",
                        "status": "subscribed",
                        "merge_fields": {"FNAME": "Alice", "LNAME": "Example"},
                    }
                ],
                "total_items": 1,
            }
        )
    )
    result = connector.list_members("L1")
    sub = result["subscribers"][0]
    assert sub["subscriber_ref"] == "subscriber_1"
    assert sub["email"] == "alice@x"
    assert sub["name"] == "Alice Example"
    assert "subscriber_id" not in sub
