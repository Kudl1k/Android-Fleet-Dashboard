# M4.5 safe hardware and operation acceptance

Hardware acceptance is **BLOCKED**, not passed. A localhost preflight was actually
attempted with `curl --max-time 3 -s -o /dev/null -w '%{http_code}'
http://127.0.0.1:9000/health`: exit 7, HTTP `000`. This runner could not establish a
backend connection. No Samsung operation was submitted, no screenshot captured,
and no destructive device action performed.

| Check | Result | Evidence |
|---|---|---|
| Samsung approved properties | BLOCKED | Backend unreachable |
| Samsung installed application listing | BLOCKED | Backend unreachable |
| Samsung state | BLOCKED | Backend unreachable |
| Samsung protected screenshot and image validity | BLOCKED | Backend unreachable |
| Runtime screenshot unauthorized rejection | BLOCKED | Backend unreachable |
| Runtime screenshot expiry and cleanup | BLOCKED | Backend unreachable |
| Runtime operation transitions/history/audit | BLOCKED | Backend unreachable |
| Offline, timeout, cancellation, restart and screenshot retention fixtures | PASS | `PYTHONPATH=backend/src .venv/bin/pytest backend/tests/test_control.py -q`: 34 passed |
| Safe acceptance utility regression checks | PASS | `.venv/bin/pytest backend/tests/test_m4_safe_acceptance.py -q`: 20 passed |
| Utility Ruff lint and formatting | PASS | `.venv/bin/ruff check scripts/m4_safe_acceptance.py backend/tests/test_m4_safe_acceptance.py`; corresponding `ruff format --check` |

These isolated tests do not establish hardware or deployment acceptance.

## Repeatable safe REST acceptance

`scripts/m4_safe_acceptance.py` requires an explicit registered device identifier
and an administrator bearer token supplied only via the `M4_ACCEPTANCE_TOKEN`
environment variable. Obtain the token through a local secret workflow; do not
paste it into commands, terminal transcripts or reports. After deployment and
coordinator approval, run:

```sh
.venv/bin/python scripts/m4_safe_acceptance.py --device-id '<registered Samsung identifier>'
```

The script permits only local HTTP backend URLs, disables proxies and redirects,
and submits only `state`, `properties`, `apps.list` and `screenshot`. It polls for
terminal state and the asynchronously appended successful audit record within a
finite positive deadline, checks operation history, validates
PNG framing and chunk checksums, and verifies unauthenticated screenshot denial.
It does not display package/property values, write or render screenshot bytes,
print tokens, or echo backend errors. Its output is sanitized status and image
metadata only. Polling may miss brief running states; it records observed states
rather than inventing them.

The utility does not change production screenshot retention or wait through the
default retention period. Runtime expiry acceptance remains a separate controlled
check; do not claim it passed based on the fixture test. Reboot, install,
uninstall, force-stop, bootloader/recovery and arbitrary shell acceptance are
intentionally NOT RUN on hardware. Root was never requested.
