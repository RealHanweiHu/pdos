"""Test tree hygiene (D28): folders are packages and iCloud copies are never collected."""

from fnmatch import fnmatch
from pathlib import Path

from conftest import collect_ignore_glob

TESTS = Path(__file__).resolve().parent


def ignored(path):
    return any(fnmatch(str(path), str(TESTS / pattern)) for pattern in collect_ignore_glob)


def test_every_test_folder_below_the_root_is_a_package():
    # Without __init__.py, pytest imports a folder's files by bare file name, so two
    # files with the same name in different folders collide.
    missing = sorted(
        str(folder.relative_to(TESTS))
        for folder in TESTS.rglob("*")
        if folder.is_dir()
        and "__pycache__" not in folder.parts
        and not any(ignored(parent) for parent in (folder, *folder.parents))
        and any(folder.glob("*.py"))
        and not (folder / "__init__.py").exists()
    )
    assert not missing, missing


def test_icloud_numbered_copies_are_ignored():
    for copy in ("agent/kernel/test_run_continuation 2.py", "ui/test_x 12.py", "kernel 2"):
        assert ignored(TESTS / copy), copy
    for real in ("agent/kernel/test_run_continuation.py", "projects/planning_engine"):
        assert not ignored(TESTS / real), real
