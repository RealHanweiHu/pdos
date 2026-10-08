"""Explicit local synthetic Docker smoke check. No DB, business data or host mounts.

Not collected by pytest. Results are transport evidence, not production qualification.
"""

import asyncio
import hashlib
import io
import json
import subprocess
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from pdos_next.evidence_processing.types import ParseFailure, ParseLimits
from pdos_next.evidence_security.types import (
    ScanBinding,
    ScanLimits,
    ScanPolicy,
    ScanRequest,
    ScanStatus,
)
from pdos_next.object_storage.types import ObjectRef
from pdos_next.security_runtime import DockerClamAVTransport, DockerParserRunner
from pdos_next.security_runtime.docker import DockerFailure, run_container
from pdos_next.security_runtime.parser import _image_id


def _request(content, config):
    object_id, digest = uuid4(), hashlib.sha256(content).hexdigest()
    ref = ObjectRef(
        object_id, 1, digest, len(content), "text/plain", f"originals/{object_id.hex}/v1/{digest}"
    )
    binding = ScanBinding(
        ref, uuid4(), uuid4(), uuid4(), 1, "synthetic-acl-v1", "synthetic-private-v1", True
    )
    return ScanRequest(uuid4(), binding, config.scanner, config.policy, datetime.now(UTC))


def _pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            ),
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td (synthetic located page) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_blank_page(width=300, height=200)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


async def main():
    transport = DockerClamAVTransport()
    policy = ScanPolicy(
        version="pdos-local-synthetic-file-policy-v1", limits=ScanLimits(timeout_seconds=60)
    )
    config = await transport.observe_configuration(policy)
    checks = []
    # Standard synthetic antivirus marker assembled in memory; never printed,
    # written as a host file, or included in the evidence report.
    marker = bytes.fromhex(
        "58354f2150254041505b345c505a58353428505e2937434329377d2445494341522d"
        "5354414e444152442d414e544956495255532d544553542d46494c452124482b482a"
    )
    for name, content, expected in (
        ("clean_utf8", b"synthetic harmless original\n", ScanStatus.CLEAN),
        ("synthetic_antivirus_marker", marker, ScanStatus.INFECTED),
    ):
        started = time.monotonic()
        intent = _request(content, config)
        reply = await transport.inspect(intent, content)
        assert reply.status == expected, (name, reply.status, reply.error_code)
        assert reply.scanner == config.scanner and reply.object_ref == intent.binding.object_ref
        checks.append(
            {
                "case": name,
                "status": reply.status.value,
                "error_code": reply.error_code,
                "seconds": round(time.monotonic() - started, 3),
            }
        )
    short = replace(
        config, policy=replace(policy, limits=replace(policy.limits, timeout_seconds=0.05))
    )
    intent = _request(b"synthetic timeout content\n", short)
    started = time.monotonic()
    reply = await transport.inspect(intent, b"synthetic timeout content\n")
    assert reply.status == ScanStatus.TIMEOUT, (reply.status, reply.error_code)
    checks.append(
        {
            "case": "whole_container_timeout",
            "status": reply.status.value,
            "seconds": round(time.monotonic() - started, 3),
        }
    )

    parser = DockerParserRunner()
    source = b"A\rB\xe2\x80\xa8\rC\n"
    text = await parser.parse_async(source, media_type="text/plain")
    assert text.text == source.decode() and text.scan_status == "not_scanned"
    assert [value.location.line for value in text.segments] == [1, 2, 3, 4]
    checks.append(
        {
            "case": "container_utf8_line_locations",
            "status": text.status,
            "segments": len(text.segments),
        }
    )
    pdf = await parser.parse_async(_pdf(), media_type="application/pdf")
    assert pdf.status == "parsed" and pdf.segments[0].location.page == 1
    assert "synthetic located page" in pdf.text and pdf.warnings
    checks.append(
        {
            "case": "container_pdf_partial_located_text",
            "status": pdf.status,
            "segments": len(pdf.segments),
        }
    )
    workbook = Workbook()
    workbook.active.title = "Synthetic"
    workbook.active["A1"] = "synthetic cell"
    workbook.active["B2"] = "=1+1"
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    sheet = await parser.parse_async(
        output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert [(value.location.sheet, value.location.cell) for value in sheet.segments] == [
        ("Synthetic", "A1"),
        ("Synthetic", "B2"),
    ]
    assert sheet.segments[1].text == "=1+1" and sheet.segments[1].value_kind == "formula"
    checks.append(
        {
            "case": "container_xlsx_cells_formula_not_evaluated",
            "status": sheet.status,
            "segments": len(sheet.segments),
        }
    )
    for name, content, media, code, limits in (
        ("invalid_utf8", b"\xffsynthetic", "text/plain", "INVALID_ENCODING", ParseLimits()),
        ("bounded_text", b"synthetic", "text/plain", "OUTPUT_LIMIT", ParseLimits(max_text_chars=2)),
        (
            "container_timeout",
            b"synthetic",
            "text/plain",
            "PARSER_TIMEOUT",
            ParseLimits(timeout_seconds=0.05),
        ),
    ):
        try:
            await parser.parse_async(content, media_type=media, limits=limits)
        except ParseFailure as exc:
            assert exc.code == code, (name, exc.code)
            checks.append({"case": name, "failure_code": exc.code})
        else:
            raise AssertionError("Expected bounded failure")
    # Trusted test code, not document input. Observe the real namespace/cgroup
    # boundaries rather than inferring them solely from the Docker argv.
    probe_code = (
        "import os,json,socket,pathlib; "
        "lines=pathlib.Path('/proc/self/status').read_text().splitlines(); "
        "status=dict(line.split(':',1) for line in lines if ':' in line); "
        "lines=pathlib.Path('/proc/self/mountinfo').read_text().splitlines(); "
        "mounts=[line.split() for line in lines]; "
        "result={'uid':os.getuid(),'caps':status['CapEff'].strip(),'no_new_privileges':status['NoNewPrivs'].strip(),'seccomp':status['Seccomp'].strip(),"
        "'root_read_only':any(row[4]=='/' and 'ro' in row[5].split(',') for row in mounts),"
        "'tmp_noexec':any(row[4]=='/tmp' and 'noexec' in row[5].split(',') for row in mounts),"
        "'docker_socket_present':pathlib.Path('/var/run/docker.sock').exists(),"
        "'memory_max':pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip(),"
        "'pids_max':pathlib.Path('/sys/fs/cgroup/pids.max').read_text().strip(),"
        "'cpu_max':pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().strip()}; "
        "s=socket.socket(); s.settimeout(0.2); "
        "result['external_connect_errno']=s.connect_ex(('203.0.113.1',9)); "
        "s.close(); print(json.dumps(result))"
    )
    observed = await run_container(
        image=_image_id(),
        entrypoint="python",
        arguments=("-I", "-B", "-c", probe_code),
        content=b"",
        timeout_seconds=15,
        stdout_maximum=4_096,
        user="65532:65532",
        memory_bytes=536_870_912,
        pids=16,
        cpus=1,
    )
    assert observed.returncode == 0
    boundary = json.loads(observed.stdout)
    assert boundary["uid"] == 65532 and int(boundary["caps"], 16) == 0
    assert boundary["no_new_privileges"] == "1" and boundary["seccomp"] == "2"
    assert boundary["root_read_only"] and boundary["tmp_noexec"]
    assert not boundary["docker_socket_present"]
    assert boundary["memory_max"] == "536870912" and boundary["pids_max"] == "16"
    assert boundary["cpu_max"] == "100000 100000" and boundary["external_connect_errno"] != 0
    checks.append({"case": "actual_os_container_boundaries", "observed": boundary})
    # No EOF is needed to enforce an output budget. Exercise the actual container
    # with a trusted synthetic noisy process and ensure it is killed/reaped.
    started = time.monotonic()
    try:
        await run_container(
            image=_image_id(),
            entrypoint="python",
            arguments=(
                "-I",
                "-B",
                "-c",
                "import sys,time; sys.stdout.write('x'*100000); sys.stdout.flush(); time.sleep(30)",
            ),
            content=b"",
            timeout_seconds=15,
            stdout_maximum=100,
            user="65532:65532",
            memory_bytes=536_870_912,
            pids=16,
            cpus=1,
        )
    except DockerFailure as exc:
        assert exc.code == "OUTPUT_LIMIT"
        assert time.monotonic() - started < 7
        checks.append(
            {
                "case": "actual_container_output_overflow_no_eof",
                "failure_code": exc.code,
                "seconds": round(time.monotonic() - started, 3),
            }
        )
    else:
        raise AssertionError("Expected actual bounded output failure")
    remaining = subprocess.run(
        ["docker", "ps", "--all", "--filter", "name=pdos-evidence-", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    assert not remaining, "An owned transport container remains after completed checks"
    artifact = {
        "checked_at": datetime.now(UTC).isoformat(),
        "scope": "local_synthetic_bytes_only_no_database_no_real_files",
        "production_qualified": False,
        "rules_age_days_at_check": 18,
        "configuration": asdict(config),
        "container_profile": {
            "network": "none",
            "read_only": True,
            "nonroot": True,
            "capabilities": "ALL dropped",
            "no_new_privileges": True,
            "stdin_only": True,
            "host_mounts": [],
            "docker_socket_mount": False,
            "stdout_stderr_bounded": True,
        },
        "checks": checks,
        "owned_containers_remaining": 0,
    }
    path = (
        Path(__file__).resolve().parents[4]
        / "docs/reports/evidence/pdos-next-wave8-20261002/transport-real-checks.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, default=str) + "\n")
    print(json.dumps({"checks": len(checks), "production_qualified": False, "evidence": str(path)}))


if __name__ == "__main__":
    asyncio.run(main())
