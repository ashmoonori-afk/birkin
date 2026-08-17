# Unused Feature Revalidation Decision Matrix

Base: `origin/main` `fc34334b0e095fa14e6ad67686ece8547ad61aa9`

| Candidate | Decision | Production and dynamic references | Public/docs/package contract | Compatibility action |
| --- | --- | --- | --- | --- |
| `pyproject.toml` `office` extra and `openpyxl>=3.1.5,<4` | KEEP | Office Work OS v2 routes XLSX creation through `birkin.office.create` to `birkin.office.create_backends.write_xlsx`, which loads the optional `openpyxl` backend. Office dogfood also reopens generated XLSX files with `openpyxl`. | README.md, README.ko.md, bundled Office skills, adapter provenance, package metadata tests, and the three-OS Office wheel smoke publish and verify the extra. | No code change. Preserve the extra and backend range. |
| `birkin.workspace.theme.web_variables()` | KEEP | No in-repository caller was found; the web surface currently projects `contract()` and applies roles in JavaScript. | It is an importable helper on the canonical `birkin.workspace.theme` module and returns the published CSS custom-property mapping. Removing it solely from zero internal references would risk downstream import breakage. | Preserve it. Canonicalize legacy `birkin.workspace_theme` as a re-export from `birkin.workspace.theme`, including `web_variables`. |
| `birkin.browser_aside_frames` | DELETE | Only `tests/test_browser_aside_frames.py` imports it. Production frame capture uses `browser_aside_playwright`, `browser_aside_store`, `browser_aside_orchestration`, `browser_aside_service`, and the web frame API; it does not use `BrowserFrameScheduler` or `frame_context_record`. | Added in `b18e4e7`, absent from README/skills/plugins and package re-exports. It ships only because the wheel includes the whole `birkin` package. | Before deletion, capture a failing package/import E2E that requires canonical Browser Aside modules to import from a built wheel and requires the shadow module to be absent. Document removal; retain no misleading compatibility shim for an unintegrated internal module. |
| `birkin.browser_aside_session` | DELETE | Only `tests/test_browser_aside_architecture.py` imports it. Production session generation, tabs, actions, revisions, and stale-token checks live in `browser_aside_playwright`, `browser_aside_lifecycle`, `browser_aside_engine`, `browser_aside_orchestration`, and `browser_aside_service`. | Added in `b18e4e7`, absent from README/skills/plugins and package re-exports. Its standalone model duplicates but does not enforce production behavior. | Before deletion, capture the same failing package/import E2E and preserve canonical production imports. Document removal; do not retain a false public compatibility surface. |

## Compatibility assessment

- Zero static references did not decide any outcome by itself.
- Office dependencies are retained because current production and distribution contracts use them.
- `web_variables()` is retained because its public module location and stable semantic output make downstream use plausible even without an in-repository caller.
- The two Browser Aside modules are deletion candidates only because history, imports, production call paths, documentation, exports, and packaging were all checked and show isolated test-only shadow implementations. Their deletion remains blocked until the RED package/import proof exists.
