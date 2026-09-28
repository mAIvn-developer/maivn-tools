from __future__ import annotations

import io
import urllib.request
from email.message import Message
from urllib.response import addinfourl

import pytest

from maivn_tools.runtime import ConnectorError, HttpClient, HttpRequest
from maivn_tools.runtime.http import UrllibTransport


class _FixtureResponse(addinfourl):
    msg: str


def _redirect_transport(
    monkeypatch: pytest.MonkeyPatch, destination: str
) -> list[urllib.request.Request]:
    requests: list[urllib.request.Request] = []

    class LocalFixtureHandler(urllib.request.BaseHandler):
        def default_open(self, request: urllib.request.Request) -> addinfourl:
            requests.append(request)
            headers = Message()
            status = 200
            if len(requests) == 1:
                headers['Location'] = destination
                status = 302
            response = _FixtureResponse(io.BytesIO(b'{}'), headers, request.full_url, status)
            response.msg = 'Found' if status == 302 else 'OK'
            return response

    build_opener = urllib.request.build_opener

    def local_opener(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
        return build_opener(LocalFixtureHandler(), *handlers)

    def local_urlopen(request: urllib.request.Request, *, timeout: float) -> addinfourl:
        return local_opener().open(request, timeout=timeout)

    monkeypatch.setattr(urllib.request, 'build_opener', local_opener)
    monkeypatch.setattr(urllib.request, 'urlopen', local_urlopen)
    return requests


@pytest.mark.parametrize(
    'destination',
    [
        'https://attacker.invalid/collect',
        'http://api.example.test/downgrade',
        'https://api.example.test:8443/other-service',
        'https://user:password@api.example.test/path',
    ],
)
def test_transport_refuses_redirect_before_forwarding_credentials(
    monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    requests = _redirect_transport(monkeypatch, destination)
    client = HttpClient(transport=UrllibTransport(), sleep=lambda _: None)
    with pytest.raises(ConnectorError, match='redirect'):
        client.get('https://api.example.test/start', headers={'Authorization': 'Bearer sentinel'})
    assert len(requests) == 1


@pytest.mark.parametrize('destination', ['/next', 'https://api.example.test:443/next'])
def test_transport_preserves_same_origin_redirects(
    monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    requests = _redirect_transport(monkeypatch, destination)
    response = UrllibTransport().send(
        HttpRequest('GET', 'https://api.example.test/start', {'Authorization': 'Bearer sentinel'})
    )
    assert response.status == 200
    assert len(requests) == 2
    assert requests[-1].get_header('Authorization') == 'Bearer sentinel'
