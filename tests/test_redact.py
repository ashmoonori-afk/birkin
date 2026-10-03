"""Secret masking at the tool-result choke point.

Every native tool result passes through ``ToolRegistry.execute``. A shell
command that echoes an API key, a ``read_file`` on ``.env``, or a web page
containing a token all flow straight into the model's context (and from there
into a transcript on disk and a Telegram reply) unless something masks them.
"""

from __future__ import annotations

import json

import pytest

from birkin import redact
from birkin.tools import Tool, ToolContext, ToolRegistry, ToolResult

ANTHROPIC = "sk-ant-api03-AbCdEf0123456789ZyXwVu"
GITHUB = "ghp_AbCdEf0123456789ZyXwVuTsRq"
JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"
)


class TestRedactSensitiveText:
    """Given a text block, When redacted, Then no secret material survives."""

    def test_masks_anthropic_key_and_keeps_surrounding_text(self) -> None:
        out = redact.redact_sensitive_text(f"key is {ANTHROPIC} ok")
        assert ANTHROPIC not in out
        assert out.startswith("key is ")
        assert out.endswith(" ok")

    def test_masks_github_pat(self) -> None:
        assert GITHUB not in redact.redact_sensitive_text(f"token={GITHUB}")

    def test_masks_authorization_header(self) -> None:
        out = redact.redact_sensitive_text("Authorization: Bearer abc123def456ghi789")
        assert "abc123def456ghi789" not in out

    def test_masks_jwt(self) -> None:
        assert JWT not in redact.redact_sensitive_text(f"cookie: {JWT}")

    def test_masks_password_in_database_url(self) -> None:
        out = redact.redact_sensitive_text(
            "postgres://birkin:hunter2secret@db.internal:5432/app"
        )
        assert "hunter2secret" not in out
        assert "db.internal" in out

    def test_masks_private_key_block(self) -> None:
        block = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEAxLmnop\n-----END RSA PRIVATE KEY-----"
        )
        out = redact.redact_sensitive_text(block)
        assert "MIIEowIBAAKCAQEAxLmnop" not in out

    def test_clean_text_passes_through_unchanged(self) -> None:
        text = "def add(a: int, b: int) -> int:\n    return a + b\n"
        assert redact.redact_sensitive_text(text) == text

    def test_mask_leaks_no_head_or_tail_of_the_secret(self) -> None:
        """A head/tail mask reads like a real-but-truncated key.

        hermes hit exactly this (issue #35519): the agent read the masked value
        back out of a config file and wrote it in, destroying the credential.
        """
        out = redact.redact_sensitive_text(ANTHROPIC)
        assert "AbCdEf" not in out
        assert "ZyXwVu" not in out

    def test_empty_input_is_returned_unchanged(self) -> None:
        assert redact.redact_sensitive_text("") == ""


class TestRegistryChokePoint:
    """Given a tool that returns a secret, When executed, Then it is masked."""

    @staticmethod
    def _registry(tmp_path, content: str) -> ToolRegistry:
        ctx = ToolContext(cfg={"spill_threshold": 0}, client=None, cwd=tmp_path)
        registry = ToolRegistry(ctx)
        registry.register(
            Tool(
                name="leak",
                description="returns a secret",
                input_schema={"type": "object", "properties": {}},
                fn=lambda _input, _ctx: ToolResult(content),
            )
        )
        return registry

    def test_tool_result_secret_is_masked(self, tmp_path) -> None:
        result = self._registry(tmp_path, f"export KEY={ANTHROPIC}").execute("leak", {})
        assert ANTHROPIC not in result.content

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            (f"export KEY={ANTHROPIC}", None),
            (
                '{"password": "opaque-secret-value", "label": "plain"}',
                '{"password": "[redacted]", "label": "plain"}',
            ),
        ],
    )
    def test_post_tool_hook_receives_the_caller_redacted_text(
        self, tmp_path, content, expected
    ) -> None:
        seen: list[str] = []

        class Hooks:
            def pre_tool(self, _name, _tool_input):
                return None

            def post_tool(self, _name, _tool_input, content, _is_error):
                seen.append(content)

        ctx = ToolContext(
            cfg={"spill_threshold": 0}, client=None, cwd=tmp_path, hooks=Hooks()
        )
        registry = ToolRegistry(ctx)
        registry.register(
            Tool(
                name="leak",
                description="returns a secret",
                input_schema={"type": "object", "properties": {}},
                fn=lambda _input, _ctx: ToolResult(content),
            )
        )

        result = registry.execute("leak", {})

        assert seen == [result.content]
        if expected is None:
            assert ANTHROPIC not in seen[0]
            assert "[redacted" in seen[0]
        else:
            assert seen[0] == expected
            assert result.content == expected

    def test_error_results_are_masked_too(self, tmp_path) -> None:
        ctx = ToolContext(cfg={"spill_threshold": 0}, client=None, cwd=tmp_path)
        registry = ToolRegistry(ctx)
        registry.register(
            Tool(
                name="boom",
                description="fails with a secret",
                input_schema={"type": "object", "properties": {}},
                fn=lambda _input, _ctx: ToolResult(
                    f"auth failed for {GITHUB}", is_error=True
                ),
            )
        )
        result = registry.execute("boom", {})
        assert result.is_error is True
        assert GITHUB not in result.content

    def test_clean_tool_output_is_not_rewritten(self, tmp_path) -> None:
        result = self._registry(tmp_path, "total 4\ndrwxr-xr-x  2 lg lg").execute(
            "leak", {}
        )
        assert result.content == "total 4\ndrwxr-xr-x  2 lg lg"


class TestCookieHeaders:
    """Given a Cookie/Set-Cookie header, When redacted, Then the value is masked."""

    def test_masks_cookie_header_value(self) -> None:
        out = redact.redact_sensitive_text(
            "GET / HTTP/1.1\nCookie: sessionid=AbCdEf0123456789ZyXwV\nHost: x")
        assert "AbCdEf0123456789ZyXwV" not in out
        assert "Cookie: " + redact.SENTINEL in out
        assert "Host: x" in out

    def test_masks_set_cookie_including_attributes(self) -> None:
        out = redact.redact_sensitive_text(
            "Set-Cookie: auth=AbCdEf0123456789ZyXwV; HttpOnly; Path=/")
        assert "AbCdEf0123456789ZyXwV" not in out
        assert "HttpOnly" not in out


class TestJsonCredentialValues:
    """Given a JSON string value under a credential key, Then it is masked.

    The legacy assignment expression requires the separator right after the
    name, but a JSON key carries its closing quote there, so key/value pairs
    like ``"password": "hunter2secret"`` used to survive untouched.
    """

    @pytest.mark.parametrize(
        "key",
        [
            "password",
            "token",
            "api_key",
            "client_secret",
            "access-key",
            "credential",
            "passwd",
            "API_KEY",
        ],
    )
    def test_masks_generic_value_of_json_credential_key(self, key) -> None:
        text = json.dumps({key: "opaque-secret-value"}, ensure_ascii=False)
        assert json.loads(redact.redact_sensitive_text(text)) == {
            key: redact.SENTINEL
        }

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("two words, three", "two words, three"),
            ("quote: \" and backslash: \\", "quote: \" and backslash: \\"),
            ("line\nbreak\ttab", "line\nbreak\ttab"),
            ("\ube44\ubc00\ubc88\ud638", "\ube44\ubc00\ubc88\ud638"),
            ("x", "x"),
            ("", ""),
            ('os.getenv("X")', 'os.getenv("X")'),
            ("process.env.TOKEN", "process.env.TOKEN"),
            ("$TOKEN", "$TOKEN"),
        ],
    )
    def test_masks_every_complete_json_string_value(self, value, expected) -> None:
        text = json.dumps({"token": value, "label": "plain"})
        assert json.loads(redact.redact_sensitive_text(text)) == {
            "token": redact.SENTINEL,
            "label": "plain",
        }
        assert text != redact.redact_sensitive_text(text)

    def test_masks_nested_and_array_wrapped_objects(self) -> None:
        text = (
            '{"outer": {"password": "opaque-secret-value", "keep": 1}, '
            '"list": [{"api_key": "opaque-secret-value"}]}'
        )
        assert json.loads(redact.redact_sensitive_text(text)) == {
            "outer": {"password": redact.SENTINEL, "keep": 1},
            "list": [{"api_key": redact.SENTINEL}],
        }

    def test_masks_compact_and_pretty_crlf_documents(self) -> None:
        compact = '{"token":"opaque-secret-value","keep":2}'
        assert (
            redact.redact_sensitive_text(compact)
            == '{"token":"' + redact.SENTINEL + '","keep":2}'
        )
        pretty = '{\r\n  "token": "opaque-secret-value",\r\n  "keep": 2\r\n}'
        assert redact.redact_sensitive_text(pretty) == (
            '{\r\n  "token": "' + redact.SENTINEL + '",\r\n  "keep": 2\r\n}'
        )

    def test_masks_unicode_escaped_credential_key(self) -> None:
        text = r'{"pass\u0077ord": "opaque-secret-value"}'
        assert json.loads(redact.redact_sensitive_text(text)) == {
            "password": redact.SENTINEL
        }

    def test_masks_duplicate_secret_keys_without_reformatting(self) -> None:
        text = '{"token": "first-secret-value", "token": "second-secret-value"}'
        masked = redact.SENTINEL
        assert redact.redact_sensitive_text(text) == (
            '{"token": "' + masked + '", "token": "' + masked + '"}'
        )

    def test_masks_json_embedded_in_log_line_and_fence(self) -> None:
        assert redact.redact_sensitive_text(
            'INFO payload {"password": "opaque-secret-value"} end'
        ) == 'INFO payload {"password": "' + redact.SENTINEL + '"} end'
        assert redact.redact_sensitive_text(
            '```\n{"api_key": "opaque-secret-value"}\n```'
        ) == '```\n{"api_key": "' + redact.SENTINEL + '"}\n```'

    def test_masks_unusual_separators_without_reformatting(self) -> None:
        masked = redact.SENTINEL
        assert (
            redact.redact_sensitive_text('{"token"\t:\t"opaque-secret-value"}')
            == '{"token"\t:\t"' + masked + '"}'
        )
        assert (
            redact.redact_sensitive_text('{"token"\n: "opaque-secret-value"}')
            == '{"token"\n: "' + masked + '"}'
        )


def test_legacy_assignment_and_json_paths_do_not_interfere() -> None:
    """Both shapes in one text: each pass masks its own form."""
    text = 'token=opaque-secret-value and {"api_key": "opaque-secret-value"}'
    out = redact.redact_sensitive_text(text)
    assert "opaque-secret-value" not in out
    assert out == (
        'token=' + redact.SENTINEL + ' and {"api_key": "' + redact.SENTINEL + '"}'
    )


class TestJsonPreservation:
    """JSON that carries no credential *value* must survive untouched."""

    def test_quoted_example_inside_a_plain_string_is_preserved(self) -> None:
        text = (
            '{"docs": "set \\"password\\": \\"opaque-secret-value\\" '
            'to configure"}'
        )
        assert redact.redact_sensitive_text(text) is text

    def test_code_references_in_plain_text_stay_unchanged(self) -> None:
        for text in (
            'API_KEY=os.getenv("X")',
            "token=process.env.TOKEN",
            'config["api_key"]',
        ):
            assert redact.redact_sensitive_text(text) is text

    def test_opt_out_returns_the_json_unchanged(self) -> None:
        text = '{"password": "opaque-secret-value"}'
        assert redact.redact_tool_output(text, {"redact_secrets": False}) is text

    def test_clean_json_is_returned_by_identity(self) -> None:
        text = '{"mode": "production", "retries": 3, "verbose": true}'
        assert redact.redact_sensitive_text(text) is text

    def test_masked_json_is_stable_on_a_second_call(self) -> None:
        text = '{"password": "opaque-secret-value", "label": "plain"}'
        once = redact.redact_sensitive_text(text)
        assert redact.redact_sensitive_text(once) is once

    def test_non_string_credentials_are_left_alone(self) -> None:
        for literal in ("null", "true", "1234"):
            text = '{"token": ' + literal + '}'
            assert redact.redact_sensitive_text(text) is text

    def test_containers_are_not_replaced_wholesale(self) -> None:
        text = '{"token": {"nested": "keep-me"}, "secret": ["keep-me"]}'
        assert redact.redact_sensitive_text(text) is text

    def test_unrelated_keys_outside_the_vocabulary_are_untouched(self) -> None:
        text = '{"username": "opaque-secret-value", "note": "keep-me"}'
        assert redact.redact_sensitive_text(text) is text
