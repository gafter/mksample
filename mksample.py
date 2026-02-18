#!/usr/bin/env python3

# Copyright 2026 Neal Gafter <neal@gafter.com>. See LICENSE for details.

"""
Command-line utility to produce a fair sample of a set of files.
"""

import argparse
import heapq
import math
import os
import random
import re
import sys
import zipfile

HELP_TEXT = """mksample filename+ [ arguments ]

Produces a fair sample of a set of files. See https://github.com/gafter/mksample/blob/main/README.md

arguments:
    --dryrun
        Prints the names of the files it would add to the sample.
    --output outputdir
        Sets the name of the output directory. This argument is required.
    --exclude pattern ...
        Sets regular expression patterns of files and directories that should be ignored.
        This takes precedence over the --include patterns. To be a candidate for the
        sample, a file's simple name must be included and not excluded.
        May be specified more than once.
    --include pattern ...
        Sets regular expression patterns of files to include. If not specified, "*"
        Directories are explored as long as they are not excluded; they don't have to
        match an include pattern.
        May be specified more than once.
    --size
        Sets the probability of a file's inclusion in the sample to be based on the file size:
        Its probability of being included in a sample is proportional to the file's size.
        This is the default. --size and --uniform are mutually exclusive.
    --uniform
        Sets the probability of a file's inclusion in the sample to be uniform: every file has
        an equal probability of being included in the sample.
    --zip
        Causes files contained within zip files to be considered candidates for sampling.
        Zip files contained within zip files are ignored.
    --count n
        Designate the number of samples to be produced. 1 <= n <= 2500
"""

SKIP_BASENAME_DIR = "@eaDir"
MKSAMPLE_SKIP_FILE = ".mksample.skip"
ZIP_SEP = "!"
# Avoid log(0) in Efraimidis-Spirakis
RANDOM_EPSILON = 2**-1074


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="mksample",
        description=HELP_TEXT,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("filenames", nargs="+", metavar="filename", help="Files or directories to sample from")
    parser.add_argument("--dryrun", action="store_true", help="Print files that would be added")
    parser.add_argument("--output", required=True, metavar="outputdir", help="Output directory (required)")
    parser.add_argument("--exclude", action="append", default=[], metavar="pattern", dest="exclude_patterns")
    parser.add_argument("--include", action="append", default=None, metavar="pattern", dest="include_patterns")
    parser.add_argument("--size", action="store_true", default=True, help="Weight by file size (default)")
    parser.add_argument("--uniform", action="store_true", help="Uniform weight per file")
    parser.add_argument("--zip", action="store_true", help="Consider contents of zip files")
    parser.add_argument("--count", type=int, default=2500, metavar="n", help="Number of samples (1-2500, default 2500)")
    args = parser.parse_args(argv)

    if args.include_patterns is None:
        args.include_patterns = [".*"]  # default "*" => match all (full match)
    if args.size and args.uniform:
        parser.error("--size and --uniform are mutually exclusive")
    if args.uniform:
        args.size = False
    if not (1 <= args.count <= 2500):
        parser.error("--count must be between 1 and 2500")

    return args


def _basename(path):
    """Last path component. For zip!member use the member part."""
    if ZIP_SEP in path:
        path = path.split(ZIP_SEP, 1)[1]
    return os.path.basename(path) or "unnamed"


def _sanitize_dest_basename(base):
    """Replace path separators, NUL, and newlines so the destination name is safe."""
    return base.replace("\0", "_").replace("/", "_").replace("\\", "_").replace("\n", "_").replace("\r", "_")


def _should_skip_traversal(basename, exclude_re):
    """Skip directories and zip containers if hidden, @eaDir, or excluded."""
    if basename.startswith(".") or basename == SKIP_BASENAME_DIR:
        return True
    if exclude_re and exclude_re.search(basename) is not None:
        return True
    return False


def _should_skip_file_basename(basename, exclude_re, include_re):
    """Skip file (or zip member) if hidden, @eaDir, excluded, or not included."""
    if basename.startswith(".") or basename == SKIP_BASENAME_DIR:
        return True
    if exclude_re and exclude_re.search(basename) is not None:
        return True
    if include_re.search(basename) is None:
        return True
    return False


def _compile_patterns(patterns, option_name="pattern"):
    """Compile list of regex pattern strings to one fullmatch regex."""
    if not patterns:
        return None
    try:
        combined = "|".join(f"(?:{p})" for p in patterns)
        return re.compile(f"^(?:{combined})$")
    except re.error as e:
        sys.stderr.write(f"mksample: invalid regular expression for {option_name}: {e}\n")
        sys.exit(1)


def stage1_collect_candidates(args):
    """Produce list of (weight, path) where path may be 'zip_path!member' for zip entries."""
    exclude_re = _compile_patterns(args.exclude_patterns, "--exclude") if args.exclude_patterns else None
    include_re = _compile_patterns(args.include_patterns, "--include")
    candidates = []

    def visit(path):
        basename = _basename(path)
        if os.path.isdir(path) and ZIP_SEP not in path:
            if _should_skip_traversal(basename, exclude_re):
                return
            if os.path.isfile(os.path.join(path, MKSAMPLE_SKIP_FILE)):
                return
            try:
                for name in os.listdir(path):
                    visit(os.path.join(path, name))
            except OSError:
                pass
            return
        if args.zip and path.lower().endswith(".zip") and os.path.isfile(path):
            if _should_skip_traversal(basename, exclude_re):
                return
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    for info in zf.infolist():
                        member_path = info.filename.rstrip("/")
                        if not member_path:
                            continue
                        member_basename = os.path.basename(member_path) or "unnamed"
                        if _should_skip_file_basename(member_basename, exclude_re, include_re):
                            continue
                        if info.is_dir():
                            continue
                        k = info.file_size if args.size else 1
                        if k < 0:
                            k = 0
                        if args.size and k <= 0:
                            continue
                        candidates.append((k, path + ZIP_SEP + member_path))
            except (zipfile.BadZipFile, OSError):
                pass
            return
        if os.path.isfile(path) or (os.path.islink(path) and not os.path.isdir(path)):
            if _should_skip_file_basename(basename, exclude_re, include_re):
                return
            k = os.path.getsize(path) if args.size else 1
            if k < 0:
                k = 0
            if args.size and k <= 0:
                return
            candidates.append((k, path))
        # else: broken symlink, etc. skip

    missing = [fn for fn in args.filenames if not os.path.exists(fn)]
    if missing:
        sys.stderr.write(f"mksample: no such file or directory: {', '.join(missing)}\n")
        sys.exit(1)
    for fn in args.filenames:
        visit(os.path.abspath(fn))

    return candidates


def stage2_sample(candidates, n):
    """Efraimidis-Spirakis with min-heap: key = log(r)/k, keep top n by key."""
    if not candidates:
        return []
    n = min(n, len(candidates))
    if n == 0:
        return []
    # Min-heap of (key, path). We want the n items with largest keys.
    heap = []
    for k, path in candidates:
        r = random.random() or RANDOM_EPSILON
        # key = log(r)/k; larger k => less negative => higher key
        key = math.log(r) / k if k > 0 else math.log(r)
        if len(heap) < n:
            heapq.heappush(heap, (key, path))
        elif key > heap[0][0]:
            heapq.heapreplace(heap, (key, path))
    selected = [path for _, path in heap]
    random.shuffle(selected)
    return selected


def stage3_produce_sample(selected, outputdir, dryrun):
    """Create outputdir and write each selected file (extract from zip or hardlink)."""
    if os.path.exists(outputdir):
        sys.stderr.write(f"mksample: output directory already exists: {outputdir}\n")
        sys.exit(1)
    if dryrun:
        for fn in selected:
            print(fn)
        return
    os.makedirs(outputdir, exist_ok=False)
    open(os.path.join(outputdir, MKSAMPLE_SKIP_FILE), "a").close()
    for i, fn in enumerate(selected):
        dn = f"{i // 25:02d}"
        subdir = os.path.join(outputdir, dn)
        os.makedirs(subdir, exist_ok=True)
        base = _sanitize_dest_basename(_basename(fn))
        dfn = f"{i:04d} {base}"
        dest = os.path.join(subdir, dfn)
        if ZIP_SEP in fn:
            zip_path, member_path = fn.split(ZIP_SEP, 1)
            with zipfile.ZipFile(zip_path, "r") as zf:
                with zf.open(member_path) as src:
                    with open(dest, "wb") as out:
                        out.write(src.read())
        else:
            try:
                os.link(fn, dest)
            except OSError:
                # Cross-filesystem or permission: fallback to copy
                with open(fn, "rb") as src:
                    with open(dest, "wb") as out:
                        out.write(src.read())


def main():
    if len(sys.argv) <= 1:
        print(HELP_TEXT)
        sys.exit(0)
    args = parse_args(sys.argv[1:])
    candidates = stage1_collect_candidates(args)
    if not candidates:
        sys.stderr.write("mksample: no candidates found\n")
        sys.exit(1)
    selected = stage2_sample(candidates, args.count)
    stage3_produce_sample(selected, args.output, args.dryrun)


if __name__ == "__main__":
    main()
