#!/usr/bin/env bash
set -euo pipefail

MAX_LINES=400
VIOLATIONS=""

for f in $(find birkin -name '*.py' -not -name '__init__.py' -not -path '*__pycache__*'); do
    # Skip exceptions
    if [ -f .file-size-exceptions ] && grep -q "^$f" .file-size-exceptions 2>/dev/null; then
        continue
    fi
    LINES=$(wc -l < "$f")
    if [ "$LINES" -gt "$MAX_LINES" ]; then
        VIOLATIONS="$VIOLATIONS\n  $f: $LINES lines (max: $MAX_LINES)"
    fi
done

if [ -n "$VIOLATIONS" ]; then
    echo "Files exceeding $MAX_LINES line limit:"
    echo -e "$VIOLATIONS"
    echo ""
    echo "Split large files or add to .file-size-exceptions"
    exit 1
fi

echo "All files within $MAX_LINES line limit."
