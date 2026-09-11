"""The consent script's redirect is a fixed literal, minted with the client the refresh path uses (#1460).

``scripts/google_oauth_grant.py`` sends Google a loopback ``redirect_uri``. The client behind
``GOOGLE_CLIENT_ID`` is a Web application client — the sign-in needs one — and a Web client accepts
only a redirect registered verbatim in the console, port and trailing slash included. So the literal
must never move on its own: it is what a human registers, and the documents that human reads must
quote the same string the script sends. And the grant must be minted with the same client
``backend/google_client.py`` refreshes with, because a refresh token is only refreshable with the
secret of the client that minted it.
"""

import importlib.util
import socket
import urllib.parse
from pathlib import Path

import httpx
import pytest

from backend.config import Settings
from backend.google_client import SCOPES

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "google_oauth_grant.py"

# Every file a human reads before registering the redirect URI in the Google Cloud console.
DOCUMENTS_QUOTING_THE_REDIRECT = ("CLAUDE.md", ".env.example", "docs/SETUP.md", "docs/auth-recovery.md")


@pytest.fixture(scope="module")
def grant():
    spec = importlib.util.spec_from_file_location("google_oauth_grant", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_redirect_uri_is_fixed_and_ends_with_a_slash(grant):
    assert grant.REDIRECT_URI == "http://127.0.0.1:18765/"
    assert grant.REDIRECT_URI.endswith("/")
    assert "server_port" not in SCRIPT.read_text()


def test_the_consent_url_carries_the_fixed_redirect_and_the_reader_scopes(grant):
    url = urllib.parse.urlparse(grant.consent_url("client-id", "state-1", "challenge-1"))
    params = urllib.parse.parse_qs(url.query)

    assert f"{url.scheme}://{url.netloc}{url.path}" == grant.AUTH_URL
    assert params["redirect_uri"] == [grant.REDIRECT_URI]
    assert params["scope"] == [" ".join(SCOPES)]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"] == ["state-1"]
    assert params["code_challenge"] == ["challenge-1"]


def test_the_grant_and_the_refresh_use_the_same_client():
    source = SCRIPT.read_text()

    assert 'os.environ.get("GOOGLE_CLIENT_ID"' in source
    assert 'os.environ.get("GOOGLE_CLIENT_SECRET"' in source
    assert "GOOGLE_GRANT_" not in source
    assert {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"} <= set(Settings.model_fields)


@pytest.mark.parametrize("document", DOCUMENTS_QUOTING_THE_REDIRECT)
def test_the_documents_a_human_registers_from_quote_the_exact_literal(grant, document):
    assert grant.REDIRECT_URI in (REPO_ROOT / document).read_text()


def test_a_busy_port_names_itself_and_exchanges_nothing(grant, monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")

    def browser_must_not_open(url):
        raise AssertionError(f"a browser was opened for {url}")

    monkeypatch.setattr(grant.webbrowser, "open", browser_must_not_open)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", grant.REDIRECT_PORT))
        blocker.listen()

        assert grant.main() == 1

    assert str(grant.REDIRECT_PORT) in capsys.readouterr().out


def test_the_exchange_sends_the_redirect_uri_the_consent_request_carried(grant, monkeypatch):
    """The two redirect_uri values Google compares are one constant; a bind, a browser and an exchange are all faked."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")

    bound_to = []
    consent_params = {}
    exchange = {}

    class FakeServer:
        def handle_request(self):
            grant._CallbackHandler.code = "auth-code-1"
            grant._CallbackHandler.state = consent_params["state"][0]

        def server_close(self):
            pass

    def fake_http_server(address, handler):
        bound_to.append(address)
        return FakeServer()

    def fake_browser(url):
        consent_params.update(urllib.parse.parse_qs(urllib.parse.urlparse(url).query))

    def fake_post(url, data, timeout):
        exchange.update(data)
        return httpx.Response(200, json={"refresh_token": "rt-1"})

    monkeypatch.setattr(grant, "HTTPServer", fake_http_server)
    monkeypatch.setattr(grant.webbrowser, "open", fake_browser)
    monkeypatch.setattr(grant.httpx, "post", fake_post)

    assert grant.main() == 0

    assert bound_to == [("127.0.0.1", grant.REDIRECT_PORT)]
    assert exchange["redirect_uri"] == grant.REDIRECT_URI
    assert exchange["redirect_uri"] == consent_params["redirect_uri"][0]
    assert exchange["code"] == "auth-code-1"
    assert exchange["grant_type"] == "authorization_code"
