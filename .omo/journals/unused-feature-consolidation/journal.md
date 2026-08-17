# Unused Feature Consolidation Journal

## Decisions

- Promote only behavior exercised through public production surfaces.
- Remove duplicate Browser Aside sessions and external Office engine paths.
- Bind checkpoint state to the active canonical conversation session.
- Keep public-channel state session-local; never fall back to global state.
- Route Office requests before model execution from trusted user intent and artifact names.
- Adopt exact-pinned `python-hwpx==6.1.0` for optional local HWPX blank authoring.
- Keep Office production keyless, offline-capable, Python-only, and copy-on-write.

## Verification

- Full real-Chromium pytest suite passed before reviewer fixes.
- Reviewer findings added service-level package limits, transactional restore behavior, streaming XML guards, locked Office CI, and pre-import package-version enforcement.
- Targeted Office and trust suites passed after every reviewer fix.
- Final base-only wheel smoke passed with only Birkin, psutil, and typing-extensions installed.
- Final post-rebase full regression passed with real Chromium integration enabled.
- Five independent goal, quality, security, hands-on, and context reviews passed.
- The final release wheel passed the base-only Office matrix with network and process creation blocked.
