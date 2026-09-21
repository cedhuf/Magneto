#!/bin/sh
# Every test is a script that exits non-zero on failure. Screenshots are taken
# on request only: MAGNETO_SCREENSHOTS=1 tests/run.sh
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
fail=0
for t in test_*.py test_*.js; do
    [ "$t" = test_screenshots.py ] && [ -z "$MAGNETO_SCREENSHOTS" ] && continue
    case "$t" in *.py) cmd="$PY" ;; *) cmd=node ;; esac
    if out=$($cmd "$t" 2>&1); then
        echo "ok    $t"
    else
        echo "FAIL  $t"; echo "$out" | tail -5 | sed 's/^/      /'; fail=1
    fi
done
# The reel again, as a touch screen and as a browser that refuses sound.
for mode in TOUCH REFUSE; do
    if out=$(env "$mode=1" node test_shorts_render.js 2>&1); then
        echo "ok    test_shorts_render.js $mode=1"
    else
        echo "FAIL  test_shorts_render.js $mode=1"; echo "$out" | tail -5 | sed 's/^/      /'; fail=1
    fi
done
exit $fail
