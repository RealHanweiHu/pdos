# Wave8 · local scanner and OS parser transport

Frozen on 2026-10-02. This package has no database, domain write, confirmation,
receipt, authorization or worker-registration owner. The common original service
must authorize the object, bind its exact scope/reference/fence, persist the scan
receipt and recheck its current parsing gate before and after parsing.

## Calling contract

```python
from pdos_next.security_runtime import DockerClamAVTransport, DockerParserRunner

scanner = DockerClamAVTransport()
configuration = await scanner.observe_configuration(server_owned_scan_policy)
reply = await scanner.inspect(server_bound_scan_request, original_bytes)

parser = DockerParserRunner()
result = parser.parse(original_bytes, media_type=media_type, limits=parse_limits)
# In an existing event loop:
result = await parser.parse_async(original_bytes, media_type=media_type, limits=parse_limits)
```

Both constructors reject an image override. Scanner image is the fixed module
constant `sha256:388419d4ffc5caaa9c1557b81adf4608462d739560506a1288311e762978549e`.
Actual identity is observed with that image's `clamscan --version`, not copied
from a request. It is ClamAV 1.5.4, rules 28123 dated 2026-09-14 06:24:19.
Rules are 18 days old at this check. This is a local synthetic profile without
production qualification.

Parser image is fixed by the installed server artifact `parser-image.json`:
`sha256:6c19f8631119cadd2c199e08c2b77469509f3499f2e92788851e06237f3b8073`.
Current pure parser source hashes must match the image artifact; no host parser
fallback exists. The parser always returns `scan_status=not_scanned`. Only the
common service's independent, trusted clean scan receipt may allow parsing.

## Transport boundaries

Original bytes travel on stdin only. Document containers have no host bind mount,
Docker socket, credential environment, device or network access. Runtime uses an
immutable image, read-only root, nonroot user, dropped capabilities, no new
privileges, bounded pids/memory/CPU, and a noexec/nosuid/nodev bounded `/tmp` tmpfs.
The parser also applies CPU, address-space, file-size, core and open-file limits
before importing document libraries. This is actual Linux container namespace
and cgroup isolation; it is not proof against all kernel or container escapes.

The processing deadline includes client startup, stdin transfer and incremental
stdout/stderr reading. Output overflow aborts before EOF or full collection.
Cleanup stops the client, incrementally discards its unread pipes, force-removes
only the randomly generated owned container name, and reaps the client. Cleanup
has a bounded grace period (five seconds for removal and one for pipe/process
reaping). Unconfirmed cleanup cannot return a successful result. Cancellation is
preserved for the caller's timeout handling. No scanner signature or raw error
diagnostic is returned or stored in these evidence reports.

Scanner exit 0 alone produces clean; exit 1 produces infected; other exits produce
unknown/unavailable. Timeout and overflow cannot produce clean. ClamAV's internal
scan-time skip is disabled (`--max-scantime=0`) and size/recursion limit alerts are
enabled. Input bytes must exactly match the bound immutable object's size/hash.

## Image build provenance

The daemon's official DockerHub and ECR pull paths returned EOF. Host anonymous
official HTTPS worked. `fetch_base.py` recovered only the official linux/arm64
Python base, verifying the OCI manifest, config and all compressed layer digests
before `docker load`. `base-image.json` retains those digests. No daemon settings,
credentials or existing business image were changed.

`build.py` used that immutable config ID with the local builder and a 693.8KB
temporary context containing only two existing pure parser files, the new worker,
Dockerfile, requirements and pinned pure-Python wheels. PyPI-published wheel SHA256
values were verified. The build installed pypdf 6.19.0, openpyxl 3.1.5 and
et-xmlfile 2.0.0 inside the new image; host dependencies and shared locks were not
modified. No repository-wide context or `.env` was sent to the builder.

## Verification

24 pure checks passed with database conftest excluded:

```text
PYTHONPATH=pdos-next/server PYTHONDONTWRITEBYTECODE=1 \
pdos-next/server/.venv/bin/pytest \
--confcutdir=pdos-next/server/tests/security_runtime -p no:cacheprovider \
pdos-next/server/tests/security_runtime/test_runtime.py -q
24 passed
```

Fake processes in those unit checks validate protocol, budgets, identity mismatch,
cleanup/cancellation and absence of fallback. They do not qualify scanning.
Ruff check and format passed for the three owned source/test/container directories.

The 11 actual Docker checks are recorded in
[transport-real-checks.json](transport-real-checks.json): clean UTF-8, a standard
synthetic antivirus marker, scan timeout, text line locations including CR and
Unicode separators, partial PDF page text, XLSX cell/formula preservation, invalid
UTF-8, text output bound, parser timeout, actual OS/cgroup boundaries and a noisy
process overflowing output before EOF. Formula expressions were not evaluated;
no OCR was fabricated. The actual OS probe observed UID 65532, zero capabilities,
NoNewPrivs 1, seccomp 2, read-only root, noexec tmpfs, no Docker socket, network
unreachable and the exact 512MiB/pids16/CPU1 limits.

The noisy process deliberately would sleep 30 seconds. A real check revealed
unread subprocess pipes delaying reaping; cleanup was corrected and the final
counterexample terminates within the recorded subsecond interval. No owned
transport containers remained after the final checks. Tests used only synthetic
bytes, no real original files and no database.
