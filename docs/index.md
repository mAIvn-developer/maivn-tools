# maivn-tools

**Give your agents real-world reach.** `maivn-tools` is the official
connector layer for the [mAIvn Python SDK](https://maivn.io): it turns
external services — Gmail, Slack, GitHub, Stripe, Postgres, and 170+
more — into tools an `Agent` or `Swarm` can call, with one line of
registration each. Bring an API of your own, and the generic adapters
expose it the same way.

> [!warning]
> **Experimental — use with care.** `maivn-tools` is in early development
> (alpha). Connectors and toolsets are exercised against a mock transport in
> CI, but **most have not yet been validated end-to-end against live
> third-party provider APIs**. Request shapes, behavior, and the public surface
> may change between releases. Test against your own provider accounts before
> relying on any connector in production, and please
> [report issues](https://github.com/mAIvn-developer/maivn-tools/issues).

It ships in three parts:

- A small, public **connector kernel** (Tier 0) with auth strategies, an
  HTTP runtime, audit events, file primitives, and a test transport.
- **Generic adapters** that turn HTTP, OpenAPI, GraphQL, webhooks, and
  MCP servers into Agent- and Swarm-ready tools without writing any
  per-provider glue.
- **Provider toolsets** — `GmailToolSet`, `SlackToolSet`,
  `GitHubToolSet`, `StripeToolSet`, `AnthropicToolSet`, and friends —
  declared with the `@toolset` / `@toolify` decorators from `maivn`.
  Register a whole toolset (or a filtered subset) on an `Agent` with
  one call.

**New here?** Start with the [Quickstart](quickstart.md), skim the
[Architecture](architecture.md) to see how the layers fit, then jump to
the connector category below that matches the service you want to reach.

Install the package — it pulls the SDK automatically:

```bash
pip install maivn-tools
```

`maivn-tools` depends on `maivn` directly, so a single install command
gives you both the SDK and every connector. The package is **not**
exposed as a `maivn[tools]` extra; doing so creates circular
release-time coupling between the SDK and the add-on, which is why
`maivn[studio]` was retired in 0.3.0 as well.

## Foundations

| Page | What it covers |
| --- | --- |
| [Quickstart](quickstart.md) | The shortest path from `pip install` to a working tool on an `Agent`. |
| [Writing your own toolset](toolsets.md) | `@toolset` / `@toolify` decorators, `scope.add_toolset`, migration from builder-style. |
| [Architecture](architecture.md) | How the kernel layers fit together and where to extend. |
| [Auth & secrets](auth.md) | Auth strategies, secret resolvers, and credential safety. |
| [HTTP runtime](runtime.md) | Transport, retries, rate limits, pagination, and error normalization. |
| [Generic adapters](generic-adapters.md) | HTTP, OpenAPI, GraphQL, webhook, and MCP helpers. |
| [Files & attachments](files.md) | MIME detection, attachments, extractors, and bulk transfers. |
| [Events & audit](events.md) | Audit events, sinks, and webhook signature verification. |
| [Testing connectors](testing.md) | Using `MockTransport` and fixtures to test without live providers. |
| [Permissions & dry-run](permissions.md) | Permission flags, destructive markers, and the dry-run contract. |

## Connectors by category

### Files, storage & local data

| Doc | Toolsets |
| --- | --- |
| [Storage](connectors/storage.md) | `LocalFilesToolSet`, `BoxToolSet`, `DropboxToolSet` |

### Email & calendar

| Doc | Toolsets |
| --- | --- |
| [Email (IMAP/SMTP)](connectors/email.md) | `IMAPToolSet`, `SMTPToolSet` |
| [Google Workspace](connectors/google-workspace.md) | `GmailToolSet`, `GoogleCalendarToolSet`, `GoogleDriveToolSet` |
| [Microsoft Graph](connectors/microsoft-graph.md) | `OutlookMailToolSet`, `OutlookCalendarToolSet`, `MicrosoftFilesToolSet` |
| [Email delivery](connectors/email-delivery.md) | `ResendToolSet`, `SendGridToolSet`, `MailgunToolSet`, `PostmarkToolSet`, `AmazonSESToolSet`, `BrevoToolSet`, `MandrillToolSet`, `CustomerIOToolSet`, `LoopsToolSet`, `KlaviyoToolSet`, `MailchimpToolSet` |

### Productivity & documents

| Doc | Toolsets |
| --- | --- |
| [Google productivity](connectors/google-productivity.md) | `GoogleDocsToolSet`, `GoogleSheetsToolSet`, `GoogleSlidesToolSet` |
| [Microsoft productivity](connectors/microsoft-productivity.md) | `MicrosoftExcelToolSet`, `MicrosoftWordToolSet`, `MicrosoftPowerPointToolSet` |
| [Knowledge bases & no-code](connectors/knowledge-base.md) | `NotionToolSet`, `ConfluenceToolSet`, `AirtableToolSet` |

### Collaboration & messaging

| Doc | Toolsets |
| --- | --- |
| [Collaboration & messaging](connectors/collaboration.md) | `SlackToolSet`, `MicrosoftTeamsToolSet`, `GoogleChatToolSet`, `ZoomToolSet` |
| [Social media](connectors/social-media.md) | `XToolSet`, `MetaToolSet`, `InstagramToolSet`, `LinkedInToolSet`, `TikTokToolSet`, `YouTubeToolSet`, `RedditToolSet`, `PinterestToolSet`, `DiscordToolSet`, `TelegramToolSet`, `WhatsAppBusinessToolSet`, `MastodonToolSet`, `BlueskyToolSet`, `ThreadsToolSet`, `BufferToolSet` |

### Project & developer tools

| Doc | Toolsets |
| --- | --- |
| [Developer platforms](connectors/dev-platforms.md) | `GitHubToolSet`, `GitLabToolSet`, `BitbucketToolSet`, `AzureDevOpsToolSet` |
| [Project management](connectors/project-management.md) | `JiraToolSet`, `LinearToolSet` |
| [Support & ITSM](connectors/support-itsm.md) | `ZendeskToolSet`, `ServiceNowToolSet` |

### CRM & business

| Doc | Toolsets |
| --- | --- |
| [CRM](connectors/crm.md) | `HubSpotToolSet`, `SalesforceToolSet` |

### Databases & warehouses

| Doc | Toolsets |
| --- | --- |
| [Databases](connectors/databases.md) | `SQLiteToolSet`, `PostgresToolSet`, `MySQLToolSet`, `SQLServerToolSet`, `SupabaseToolSet` |
| [Warehouses](connectors/warehouses.md) | `SnowflakeToolSet`, `BigQueryToolSet` |
| [ETL & data movement](connectors/etl.md) | `FivetranToolSet`, `AirbyteToolSet`, `DbtCloudToolSet`, `HightouchToolSet`, `CensusToolSet`, `StitchToolSet` |

### Analytics & BI

| Doc | Toolsets |
| --- | --- |
| [Analytics & BI](connectors/analytics-bi.md) | `AmplitudeToolSet`, `MixpanelToolSet`, `SegmentToolSet`, `PostHogToolSet`, `LookerToolSet`, `TableauToolSet`, `MetabaseToolSet`, `HexToolSet`, `SigmaToolSet` |

### HR & people ops

| Doc | Toolsets |
| --- | --- |
| [HR & people ops](connectors/hr.md) | `WorkdayToolSet`, `BambooHRToolSet`, `RipplingToolSet`, `GustoToolSet`, `GreenhouseToolSet`, `LeverToolSet`, `DeelToolSet` |

### Marketing & ads

| Doc | Toolsets |
| --- | --- |
| [Marketing & ads](connectors/marketing-ads.md) | `MarketoToolSet`, `IterableToolSet`, `BrazeToolSet`, `GoogleAdsToolSet`, `MetaAdsToolSet`, `LinkedInAdsToolSet`, `TikTokAdsToolSet` |

### Payments, finance & commerce

| Doc | Toolsets |
| --- | --- |
| [Payments & finance](connectors/payments.md) | `StripeToolSet`, `SquareToolSet`, `PayPalToolSet`, `PlaidToolSet`, `QuickBooksToolSet`, `XeroToolSet`, `NetSuiteToolSet`, `RampToolSet`, `BrexToolSet`, `ChargebeeToolSet`, `RecurlyToolSet`, `BillToolSet`, `ExpensifyToolSet` |
| [E-commerce](connectors/commerce.md) | `ShopifyToolSet`, `WooCommerceToolSet`, `BigCommerceToolSet`, `MagentoToolSet`, `AmazonSellerToolSet`, `EbayToolSet`, `WalmartMarketplaceToolSet` |
| [Trading & market data](connectors/trading.md) | `AlpacaToolSet`, `PolygonToolSet`, `TradierToolSet`, `InteractiveBrokersToolSet`, `CoinbaseToolSet`, `KrakenToolSet`, `BinanceToolSet`, `SchwabToolSet` |

### AI providers

| Doc | Toolsets |
| --- | --- |
| [AI providers](connectors/ai-providers.md) | `OpenAIToolSet`, `AnthropicToolSet`, `AzureOpenAIToolSet`, `GeminiToolSet`, `BedrockToolSet`, `MistralToolSet`, `CohereToolSet`, `HuggingFaceToolSet`, `ReplicateToolSet`, `StabilityToolSet`, `ElevenLabsToolSet`, `DeepgramToolSet`, `AssemblyAIToolSet`, `TavilyToolSet`, `BraveSearchToolSet`, `SerpAPIToolSet` |
| [Vector stores](connectors/vector-stores.md) | `PineconeToolSet`, `WeaviateToolSet`, `QdrantToolSet`, `ChromaToolSet`, `MilvusToolSet` |

### Cloud & observability

| Doc | Toolsets |
| --- | --- |
| [Cloud & observability](connectors/cloud-observability.md) | `DatadogToolSet`, `SentryToolSet`, `PagerDutyToolSet`, `NewRelicToolSet`, `SplunkToolSet`, `GrafanaToolSet`, `StatuspageToolSet`, `CloudflareToolSet`, `KubernetesToolSet` |
| [AWS core](connectors/aws.md) | `AmazonS3ToolSet`, `AmazonLambdaToolSet`, `AmazonCloudWatchLogsToolSet`, `AmazonIAMToolSet` |

### Identity & security

| Doc | Toolsets |
| --- | --- |
| [Identity & security](connectors/identity-security.md) | `Auth0ToolSet`, `OktaToolSet`, `VaultToolSet`, `OnePasswordToolSet`, `BitwardenToolSet`, `DopplerToolSet`, `InfisicalToolSet`, `SnykToolSet`, `TwilioToolSet`, `JumpCloudToolSet`, `OneLoginToolSet`, `DuoToolSet` |

### Breadth & automation

| Doc | Toolsets |
| --- | --- |
| [Partner hubs](connectors/partner-hubs.md) | `WorkatoToolSet`, `PipedreamToolSet`, `MakeToolSet`, `N8nToolSet`, `ComposioToolSet`, `ZapierConnector` |

## Governance

| Page | What it covers |
| --- | --- |
| [API policy](api-policy.md) | Stable surface, semver, deprecations. |
| [Security policy](security.md) | Credential handling, destructive actions, webhook signing. |
| [Release checklist](release-checklist.md) | Gates a release must clear before it ships. |
| [Provider docs template](templates/provider.md) | Shape every new connector's docs. |

## Stability

`maivn-tools` is in active development (alpha). Public imports rooted at
`maivn_tools.*` follow semantic versioning. Modules under `_internal` or
explicitly marked experimental may change between minor releases.

Connectors are tested against an in-process mock transport (see
[Testing connectors](testing.md)); **most have not yet been validated
end-to-end against live third-party provider APIs.** Treat the provider
toolsets as experimental until you have verified them against your own
accounts, and please report any discrepancies.

## License

Apache-2.0. See [`LICENSE`](https://github.com/mAIvn-developer/maivn-tools/blob/master/LICENSE).
