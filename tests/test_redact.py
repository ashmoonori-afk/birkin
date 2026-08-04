"""Secret masking at the tool-result choke point.

Every native tool result passes through ``ToolRegistry.execute``. A shell
command that echoes an API key, a ``read_file`` on ``.env``, or a web page
containing a token all flow straight into the model's context (and from there
into a transcript on disk and a Telegram reply) unless something masks them.
"""

from __future__ import annotations

from birkin import redact
from birkin.tools import Tool, ToolContext, ToolRegistry, ToolResult

ANTHROPIC = "sk-ant-api03-AbCdEf0123456789ZyXwVu"
GITHUB = "ghp_AbCdEf0123456789ZyXwVuTsRq"
JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
       "eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk")


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
            "postgres://birkin:hunter2secret@db.internal:5432/app")
        assert "hunter2secret" not in out
        assert "db.internal" in out

    def test_masks_private_key_block(self) -> None:
        block = ("-----BEGIN RSA PRIVATE KEY-----\n"
                 "MIIEowIBAAKCAQEAxLmnop\n-----END RSA PRIVATE KEY-----")
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
        registry.register(Tool(
            name="leak", description="returns a secret",
            input_schema={"type": "object", "properties": {}},
            fn=lambda _input, _ctx: ToolResult(content)))
        return registry

    def test_tool_result_secret_is_masked(self, tmp_path) -> None:
        result = self._registry(tmp_path, f"export KEY={ANTHROPIC}").execute("leak", {})
        assert ANTHROPIC not in result.content

    def test_error_results_are_masked_too(self, tmp_path) -> None:
        ctx = ToolContext(cfg={"spill_threshold": 0}, client=None, cwd=tmp_path)
        registry = ToolRegistry(ctx)
        registry.register(Tool(
            name="boom", description="fails with a secret",
            input_schema={"type": "object", "properties": {}},
            fn=lambda _input, _ctx: ToolResult(f"auth failed for {GITHUB}",
                                               is_error=True)))
        result = registry.execute("boom", {})
        assert result.is_error is True
        assert GITHUB not in result.content

    def test_clean_tool_output_is_not_rewritten(self, tmp_path) -> None:
        result = self._registry(tmp_path, "total 4\ndrwxr-xr-x  2 lg lg").execute("leak", {})
        assert result.content == "total 4\ndrwxr-xr-x  2 lg lg"
