# Verification Economics

| claim | risk | error cost | verification cost/time | chosen path | decision | outcome | residual risk |
|---|---|---|---|---|---|---|---|
| C-001 delete-now 0 LOC | high | hidden runtime breakage | medium | AST + registration + package + tests | verify | pending | pending |
| C-002 architecture LOC ranges | high | false savings estimate | medium | pure LOC + duplicate blocks + callers | verify | pending | pending |
| C-003 deferred legacy groups | high | compatibility/data loss | high | history + config/schema/API consumers | verify | pending | pending |
