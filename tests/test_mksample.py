# Copyright 2026 The mksample authors. See LICENSE for details.

"""Tests for mksample."""

import os
import sys
import zipfile
from pathlib import Path

import pytest

# Run from repo root so mksample is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mksample as m


def test_help_no_args(capsys):
    sys.argv = ["mksample"]
    with pytest.raises(SystemExit):
        m.main()
    out, err = capsys.readouterr()
    assert "mksample filename+" in out
    assert "Produces a fair sample" in out
    assert "--output" in out
    assert err == ""


def test_help_flag(capsys):
    sys.argv = ["mksample", "--help"]
    with pytest.raises(SystemExit):
        m.parse_args(["--help"])
    # When we run main with --help argparse exits; so run parse_args on normal args
    args = m.parse_args(["x", "--output", "out"])
    assert args.output == "out"
    assert args.filenames == ["x"]


def test_count_validation():
    with pytest.raises(SystemExit):
        m.parse_args(["x", "--output", "o", "--count", "0"])
    with pytest.raises(SystemExit):
        m.parse_args(["x", "--output", "o", "--count", "2501"])
    args = m.parse_args(["x", "--output", "o", "--count", "1"])
    assert args.count == 1
    args = m.parse_args(["x", "--output", "o", "--count", "2500"])
    assert args.count == 2500


def test_size_uniform_mutually_exclusive():
    with pytest.raises(SystemExit):
        m.parse_args(["x", "--output", "o", "--size", "--uniform"])


def test_stage1_include_exclude(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "c.dat").write_text("c")

    class Args:
        exclude_patterns = []
        include_patterns = [r".*\.txt"]
        size = True
        zip = False
        filenames = [str(tmp_path)]

    args = Args()
    cands = m.stage1_collect_candidates(args)
    names = {os.path.basename(p) for _, p in cands}
    assert names == {"a.txt", "b.txt"}
    assert "c.dat" not in names

    # Exclude takes precedence
    class Args2:
        exclude_patterns = [r"a\.txt"]
        include_patterns = [r".*\.txt"]
        size = True
        zip = False
        filenames = [str(tmp_path)]
    args2 = Args2()
    cands2 = m.stage1_collect_candidates(args2)
    names2 = {os.path.basename(p) for _, p in cands2}
    assert names2 == {"b.txt"}


def test_stage1_skip_mksample_skip_dir(tmp_path):
    (tmp_path / "top.txt").write_text("x")
    skip_dir = tmp_path / "sample_out"
    skip_dir.mkdir()
    (skip_dir / m.MKSAMPLE_SKIP_FILE).touch()
    (skip_dir / "nested.txt").write_text("y")
    other = tmp_path / "other"
    other.mkdir()
    (other / "other.txt").write_text("z")

    class Args:
        exclude_patterns = []
        include_patterns = [".*"]
        size = True
        zip = False
        filenames = [str(tmp_path)]

    args = Args()
    cands = m.stage1_collect_candidates(args)
    basenames = {os.path.basename(p) for _, p in cands}
    assert "top.txt" in basenames
    assert "other.txt" in basenames
    assert "nested.txt" not in basenames


def test_stage1_skip_dot_and_eadir(tmp_path):
    (tmp_path / "normal").write_text("x")
    (tmp_path / ".hidden").write_text("x")
    (tmp_path / ".eaDir").mkdir()
    (tmp_path / ".eaDir" / "f").write_text("x")
    atea = tmp_path / "@eaDir"
    atea.mkdir()
    (atea / "f").write_text("x")

    class Args:
        exclude_patterns = []
        include_patterns = [".*"]
        size = True
        zip = False
        filenames = [str(tmp_path)]

    args = Args()
    cands = m.stage1_collect_candidates(args)
    basenames = {os.path.basename(p) for _, p in cands}
    assert "normal" in basenames
    assert ".hidden" not in basenames
    assert "@eaDir" not in basenames
    # Files inside @eaDir should not appear (dir is skipped so we don't descend)
    assert basenames <= {"normal"}


def test_stage1_directory_recursion(tmp_path):
    (tmp_path / "a").write_text("a")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b").write_text("b")

    class Args:
        exclude_patterns = []
        include_patterns = [".*"]
        size = True
        zip = False
        filenames = [str(tmp_path)]

    args = Args()
    cands = m.stage1_collect_candidates(args)
    paths = {p for _, p in cands}
    assert any("a" in p and p.endswith("a") for p in paths)
    assert any("sub" in p and "b" in p for p in paths)


def test_stage2_sample_count():
    # More candidates than count
    candidates = [(1, "a"), (1, "b"), (1, "c"), (1, "d"), (1, "e")]
    selected = m.stage2_sample(candidates, 3)
    assert len(selected) == 3
    assert len(set(selected)) == 3
    # Fewer candidates than count
    selected2 = m.stage2_sample(candidates, 10)
    assert len(selected2) == 5
    assert set(selected2) == {"a", "b", "c", "d", "e"}


def test_stage2_uniform_vs_size():
    # With uniform weights we still get n distinct; with size we get n distinct
    candidates = [(10, "big"), (1, "small1"), (1, "small2"), (1, "small3")]
    selected = m.stage2_sample(candidates, 2)
    assert len(selected) == 2
    assert len(set(selected)) == 2


def test_stage3_dryrun(capsys, tmp_path):
    (tmp_path / "f1").write_text("x")
    (tmp_path / "f2").write_text("y")

    class Args:
        exclude_patterns = []
        include_patterns = [".*"]
        size = True
        zip = False
        filenames = [str(tmp_path)]

    args = Args()
    cands = m.stage1_collect_candidates(args)
    selected = m.stage2_sample(cands, 2)
    outdir = tmp_path / "out"
    cmdline = f"mksample --output {outdir} {tmp_path}"
    m.stage3_produce_sample(selected, str(outdir), True, cmdline)
    out, _ = capsys.readouterr()
    lines = [l.strip() for l in out.strip().splitlines()]
    assert len(lines) == 2
    assert not outdir.exists()


def test_stage3_creates_mksample_skip(tmp_path):
    (tmp_path / "one").write_text("1")
    outdir = tmp_path / "out"
    selected = [str(tmp_path / "one")]
    cmdline = f"mksample --output {outdir} {tmp_path}"
    m.stage3_produce_sample(selected, str(outdir), False, cmdline)
    skip_file = outdir / m.MKSAMPLE_SKIP_FILE
    assert skip_file.is_file()
    assert skip_file.read_text() == cmdline + "\n"


def test_stage3_output_layout(tmp_path):
    (tmp_path / "one").write_text("1")
    (tmp_path / "two").write_text("2")
    outdir = tmp_path / "out"
    selected = [str(tmp_path / "one"), str(tmp_path / "two")]
    cmdline = f"mksample --output {outdir} {tmp_path}"
    m.stage3_produce_sample(selected, str(outdir), False, cmdline)
    assert outdir.exists()
    d00 = outdir / "00"
    assert d00.exists()
    files = list(d00.iterdir())
    assert len(files) == 2
    names = {f.name for f in files}
    assert any(f.startswith("0000 ") for f in names)
    assert any(f.startswith("0001 ") for f in names)
    assert any("one" in f for f in names)
    assert any("two" in f for f in names)


def test_stage3_output_dir_exists_fails(tmp_path):
    (tmp_path / "f").write_text("x")
    outdir = tmp_path / "out"
    outdir.mkdir()
    selected = [str(tmp_path / "f")]
    cmdline = f"mksample --output {outdir} {tmp_path}"
    with pytest.raises(SystemExit):
        m.stage3_produce_sample(selected, str(outdir), False, cmdline)


def test_zip_candidates(tmp_path):
    zippath = tmp_path / "a.zip"
    with zipfile.ZipFile(zippath, "w") as zf:
        zf.writestr("x.txt", "x")
        zf.writestr("y.dat", "y")

    class Args:
        exclude_patterns = []
        include_patterns = [r".*\.txt"]
        size = True
        zip = True
        filenames = [str(zippath)]

    args = Args()
    cands = m.stage1_collect_candidates(args)
    assert len(cands) == 1
    path = cands[0][1]
    assert m.ZIP_SEP in path
    assert "x.txt" in path


def test_zip_extract_in_stage3(tmp_path):
    zippath = tmp_path / "a.zip"
    with zipfile.ZipFile(zippath, "w") as zf:
        zf.writestr("inner.txt", "content")
    selected = [str(zippath) + m.ZIP_SEP + "inner.txt"]
    outdir = tmp_path / "out"
    cmdline = f"mksample --output {outdir} --zip {zippath}"
    m.stage3_produce_sample(selected, str(outdir), False, cmdline)
    outfile = outdir / "00" / "0000 inner.txt"
    assert outfile.exists()
    assert outfile.read_text() == "content"


def test_empty_candidates_exits(capsys, tmp_path):
    sys.argv = ["mksample", str(tmp_path), "--output", str(tmp_path / "out")]
    with pytest.raises(SystemExit) as exc:
        m.main()
    assert exc.value.code != 0
    _, err = capsys.readouterr()
    assert "no candidates" in err


def test_invalid_count_exits(capsys):
    sys.argv = ["mksample", "/", "--output", "/tmp/o", "--count", "9999"]
    with pytest.raises(SystemExit):
        m.main()
