from birkin.codex_session import CodexAppServerSession


def _config_values(argv: list[str]) -> set[str]:
    return {
        argv[index + 1]
        for index, value in enumerate(argv[:-1])
        if value == "-c"
    }


def test_codex_app_server_disables_plugin_hooks():
    argv = CodexAppServerSession()._build_argv()

    assert "features.plugin_hooks=false" in _config_values(argv)


def test_hook_isolation_preserves_birkin_mcp_config():
    argv = CodexAppServerSession(birkin_mcp=True)._build_argv()
    config_values = _config_values(argv)

    assert "features.plugin_hooks=false" in config_values
    assert "mcp_servers.birkin.enabled=true" in config_values
