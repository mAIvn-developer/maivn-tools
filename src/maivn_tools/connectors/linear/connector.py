"""Linear GraphQL API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.base import AuthStrategy
from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import LIST_ISSUES_OUTPUT


class _LinearApiKeyAuth(AuthStrategy):
    """Linear personal API keys go in ``Authorization`` without the Bearer prefix."""

    mode = AuthMode.API_KEY

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        self._api_key = api_key

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        headers = dict(request.get("headers") or {})
        headers["Authorization"] = self._api_key
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "header": "Authorization"}


_VIEWER_QUERY = """
query Viewer {
  viewer { id name email active organization { id name urlKey } }
}
"""

_ISSUES_QUERY = """
query Issues($first: Int!, $after: String, $filter: IssueFilter, $orderBy: PaginationOrderBy) {
  issues(first: $first, after: $after, filter: $filter, orderBy: $orderBy) {
    nodes {
      id identifier title state { name } priority assignee { id name email }
      team { id key name } createdAt updatedAt url
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_ISSUE_QUERY = """
query Issue($id: String!) {
  issue(id: $id) {
    id identifier title description state { name } priority url createdAt updatedAt
    assignee { id name email } team { id key name } labels { nodes { id name } }
  }
}
"""

_TEAMS_QUERY = """
query Teams($first: Int!, $after: String) {
  teams(first: $first, after: $after) {
    nodes { id name key description }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_PROJECTS_QUERY = """
query Projects($first: Int!, $after: String) {
  projects(first: $first, after: $after) {
    nodes { id name description state startDate targetDate url }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_USERS_QUERY = """
query Users($first: Int!, $after: String) {
  users(first: $first, after: $after) {
    nodes { id name email active admin }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_CYCLES_QUERY = """
query Cycles($first: Int!, $after: String) {
  cycles(first: $first, after: $after) {
    nodes { id name number startsAt endsAt completedAt team { id name } }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_COMMENTS_QUERY = """
query Comments($issueId: String!) {
  comments(filter: {issue: {id: {eq: $issueId}}}) {
    nodes { id body user { id name } createdAt }
  }
}
"""

_ISSUE_CREATE_MUTATION = """
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier title url } }
}
"""

_ISSUE_UPDATE_MUTATION = """
mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) { success issue { id identifier title state { name } } }
}
"""

_ISSUE_ARCHIVE_MUTATION = """
mutation IssueArchive($id: String!) {
  issueArchive(id: $id) { success entity { id archivedAt } }
}
"""

_COMMENT_CREATE_MUTATION = """
mutation CommentCreate($input: CommentCreateInput!) {
  commentCreate(input: $input) { success comment { id body url } }
}
"""


@toolset(prefix="linear")
class LinearToolSet:
    """A connector for the Linear GraphQL API.

    Args:
        api_key: Linear personal API key, or an OAuth bearer token (in which case
            set ``use_bearer=True``).
        use_bearer: Treat the credential as a bearer token rather than an API key.
        base_url: API root.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="linear",
        display_name="Linear",
        version="0.1.0",
        description="Manage Linear issues, projects, teams, and cycles.",
        auth_modes=(AuthMode.API_KEY, AuthMode.OAUTH2_AUTH_CODE),
        scopes={
            "read": "Read issues, teams, and projects.",
            "write": "Create and update issues.",
            "issues:create": "Create new issues.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developers.linear.app/docs/graphql/working-with-the-graphql-api",
        homepage_url="https://linear.app/",
        tags=("issue-tracker", "project-management"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        use_bearer: bool = False,
        base_url: str = "https://api.linear.app/graphql",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.connection = connection
        auth: AuthStrategy = BearerTokenAuth(api_key) if use_bearer else _LinearApiKeyAuth(api_key)
        self._client = HttpClient(
            base_url="",
            auth=auth,
            transport=transport,
            default_headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        self._endpoint = base_url

    @property
    def client(self) -> HttpClient:
        return self._client

    def _execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        response: dict[str, Any] = self._client.post(self._endpoint, json=payload).json()
        if "errors" in response:
            raise ValueError(f"Linear GraphQL error: {response['errors']}")
        data: dict[str, Any] = response.get("data", {})
        return data

    # MARK: - Identity

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def viewer(self) -> dict[str, Any]:
        """Return the authenticated user (``viewer``).

        Returns ``{"viewer": {"id": ..., "name": ..., "email": ...,
        "organization": {...}}}``. Use to confirm the token works.
        """
        return self._execute(_VIEWER_QUERY)

    # MARK: - Teams & users

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_teams(self, *, first: int = 25, after: str | None = None) -> dict[str, Any]:
        """List workspace teams.

        Returns the raw Linear ``{"teams": {"nodes": [...], "pageInfo": ...}}``
        response. Each team has ``id``, ``name``, ``key`` (e.g. ``ENG``),
        and ``description``.
        """
        if first < 1 or first > 250:
            raise ValueError("first must be between 1 and 250")
        return self._execute(_TEAMS_QUERY, {"first": first, "after": after})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(self, *, first: int = 25, after: str | None = None) -> dict[str, Any]:
        """List users in the workspace."""
        return self._execute(_USERS_QUERY, {"first": first, "after": after})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_projects(self, *, first: int = 25, after: str | None = None) -> dict[str, Any]:
        """List projects."""
        return self._execute(_PROJECTS_QUERY, {"first": first, "after": after})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_cycles(self, *, first: int = 25, after: str | None = None) -> dict[str, Any]:
        """List cycles."""
        return self._execute(_CYCLES_QUERY, {"first": first, "after": after})

    # MARK: - Issues

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_ISSUES_OUTPUT)
    def list_issues(
        self,
        *,
        first: int = 25,
        after: str | None = None,
        filter: dict[str, Any] | None = None,
        order_by: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Linear issues with optional filter.

        Best first tool for issue triage. By default returns compact
        summaries with a stable ``issue_ref`` (``issue_1``, ``issue_2``,
        ...) plus the Linear identifier (e.g. ``ENG-123``), title, status,
        priority, assignee, team key, and update timestamp. The Linear
        identifier is the canonical user-facing handle and is safe to show
        in final answers; the GraphQL ``id`` (UUID) is an internal handle
        and is omitted unless ``include_ids=True``.

        Set ``include_metadata=False`` to receive the raw Linear GraphQL
        ``{"issues": {"nodes": [...], "pageInfo": ...}}`` response. Example
        filter: ``{"team": {"key": {"eq": "ENG"}}}``.
        """
        if first < 1 or first > 250:
            raise ValueError("first must be between 1 and 250")
        variables: dict[str, Any] = {"first": first, "after": after}
        if filter is not None:
            variables["filter"] = filter
        if order_by is not None:
            if order_by not in {"createdAt", "updatedAt"}:
                raise ValueError("order_by must be 'createdAt' or 'updatedAt'")
            variables["orderBy"] = order_by
        data = self._execute(_ISSUES_QUERY, variables)
        if not include_metadata:
            return data
        issues_block: dict[str, Any] = data.get("issues") or {}
        nodes: list[Any] = issues_block.get("nodes") or []
        summaries: list[dict[str, Any]] = []
        for index, node in enumerate(nodes, start=1):
            if not isinstance(node, dict):
                continue
            node_dict = cast(dict[str, Any], node)
            summaries.append(self._issue_summary(node_dict, index=index, include_ids=include_ids))
        page_info: dict[str, Any] = issues_block.get("pageInfo") or {}
        return {
            "issues": summaries,
            "pageInfo": page_info,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_issue(self, issue_id: Any) -> dict[str, Any]:
        """Return one issue by ID (UUID or shortcut like ``ENG-123``).

        ``issue_id`` accepts the Linear identifier string, a UUID string, a
        dict returned by :meth:`list_issues` (looking up ``identifier`` or
        ``issue_id``), or a list of such dicts.
        """
        resolved = self._extract_issue_id(issue_id)
        return self._execute(_ISSUE_QUERY, {"id": resolved})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_issue(
        self,
        *,
        team_id: str,
        title: str,
        description: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        label_ids: list[str] | None = None,
        state_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Linear issue.

        Returns ``{"issueCreate": {"success": True, "issue": {"id": ...,
        "identifier": ..., "title": ..., "url": ...}}}``.
        """
        if not team_id or not title:
            raise ValueError("team_id and title must be non-empty")
        input_: dict[str, Any] = {"teamId": team_id, "title": title}
        if description is not None:
            input_["description"] = description
        if assignee_id is not None:
            input_["assigneeId"] = assignee_id
        if priority is not None:
            input_["priority"] = priority
        if label_ids is not None:
            input_["labelIds"] = label_ids
        if state_id is not None:
            input_["stateId"] = state_id
        if project_id is not None:
            input_["projectId"] = project_id
        return self._execute(_ISSUE_CREATE_MUTATION, {"input": input_})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_issue(self, issue_id: Any, fields: dict[str, Any]) -> dict[str, Any]:
        """Update a Linear issue.

        ``issue_id`` accepts the identifier string, a UUID string, or a
        dict/list from :meth:`list_issues`.
        """
        resolved = self._extract_issue_id(issue_id)
        if not fields:
            raise ValueError("fields must be a non-empty dict")
        return self._execute(_ISSUE_UPDATE_MUTATION, {"id": resolved, "input": fields})

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def archive_issue(self, issue_id: Any) -> dict[str, Any]:
        """Archive a Linear issue (soft-delete).

        Destructive: confirm with the user. ``issue_id`` accepts the
        identifier string, a UUID string, or a dict/list from
        :meth:`list_issues`.
        """
        resolved = self._extract_issue_id(issue_id)
        return self._execute(_ISSUE_ARCHIVE_MUTATION, {"id": resolved})

    # MARK: - Comments

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_comments(self, issue_id: Any) -> dict[str, Any]:
        """List comments on an issue.

        ``issue_id`` accepts the identifier string, a UUID string, or a
        dict/list from :meth:`list_issues`.
        """
        resolved = self._extract_issue_id(issue_id)
        return self._execute(_COMMENTS_QUERY, {"issueId": resolved})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_comment(self, *, issue_id: Any, body: str) -> dict[str, Any]:
        """Comment on an issue.

        ``issue_id`` accepts the identifier string, a UUID string, or a
        dict/list from :meth:`list_issues`.
        """
        resolved = self._extract_issue_id(issue_id)
        if not body:
            raise ValueError("body must be a non-empty string")
        return self._execute(
            _COMMENT_CREATE_MUTATION,
            {"input": {"issueId": resolved, "body": body}},
        )

    # MARK: - Raw GraphQL

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def graphql(
        self,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run an arbitrary GraphQL query or mutation. Use sparingly."""
        if not query:
            raise ValueError("query must be a non-empty string")
        return self._execute(query, variables)

    # MARK: - Internal

    @staticmethod
    def _issue_summary(
        node: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        state: Any = node.get("state") or {}
        assignee: Any = node.get("assignee") or {}
        team: Any = node.get("team") or {}
        summary: dict[str, Any] = {
            "issue_ref": f"issue_{index}",
            "identifier": node.get("identifier", ""),
            "title": node.get("title", ""),
            "status": LinearToolSet._nested_str(state, "name"),
            "priority": node.get("priority", 0),
            "assignee": LinearToolSet._nested_str(assignee, "name"),
            "team": LinearToolSet._nested_str(team, "key"),
            "updated_at": node.get("updatedAt", ""),
            "url": node.get("url", ""),
        }
        if include_ids:
            summary["issue_id"] = node.get("id", "")
        return summary

    @staticmethod
    def _nested_str(value: Any, key: str) -> Any:
        """Return ``value[key]`` (default ``""``) when ``value`` is a dict, else ``""``."""
        if isinstance(value, dict):
            nested = cast(dict[str, Any], value)
            return nested.get(key, "")
        return ""

    @staticmethod
    def _extract_issue_id(candidate: Any) -> str:
        """Pull a Linear issue handle from an arbitrary value.

        Accepts the Linear identifier string (``ENG-123``), a UUID string,
        a dict returned by :meth:`list_issues` (looking up ``identifier``,
        ``issue_id``, or ``id``), or a list of such dicts.
        """
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("issue_id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            candidate_dict = cast(dict[str, Any], candidate)
            for key in ("identifier", "issue_id", "id"):
                value: Any = candidate_dict.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(candidate, list | tuple):
            sequence = cast("list[Any] | tuple[Any, ...]", candidate)
            for item in sequence:
                try:
                    return LinearToolSet._extract_issue_id(item)
                except ValueError:
                    continue
        raise ValueError(f"could not extract Linear issue id from: {candidate!r}")
