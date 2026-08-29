# Repository Agent Rules

## Commit and push gate

Whenever the user asks to commit and push, all three gates are mandatory before
staging the final change:

1. Run the relevant CLI tests and manually exercise the affected CLI surface,
   including `--help`, a successful command, and one invalid input.
2. Update and cross-check both `README.md` and `README.ko.md` against the
   behavior being published.
3. Review the changed trust boundaries, run the relevant security regression
   tests, and run an available static security scan.

Do not commit or push until every gate passes. Preserve unrelated user files and
report any unavailable check explicitly.

## Language policy

Birkin-owned user-facing copy, prompts, errors, recovery actions, progress, and
accessibility text are Korean. Source code, identifiers, protocol fields,
stable error codes, logs, telemetry, and developer diagnostics remain English.

Translate typed machine data in the presentation layer. Do not translate CLI
or API names, schema keys, test selectors, or security/error codes, and do not
expose raw exceptions, enums, cursors, paths, process identifiers, or receipt
JSON as the primary user-facing explanation. The public contract is documented
in `docs/language-policy.md`.
