# mksample

Make a fair sampling of files from a set of files and directories. The tool collects file candidates, samples them at random (with optional size-weighted or uniform probability), and writes the sample into a numbered directory layout.

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/gafter/mksample.git && cd mksample
   ```

2. **Create a virtual environment**
   ```bash
   python3 -m venv venv
   ```

3. **Activate the virtual environment and install dependencies**
   ```bash
   source venv/bin/activate   # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. **Put the script on your PATH**  
   Create a symbolic link from the repository’s `mksample` script to a directory on your PATH (for example `~/bin` or `/usr/local/bin`):
   ```bash
   ln -s "$(pwd)/mksample" ~/bin/mksample
   ```
   The script resolves its installation directory even when invoked via this symlink, so it will find the venv and `mksample.py` in the repo.

## Command line

```text
mksample filename+ [ arguments ]
```

**Positional arguments**

- **filename** (one or more): Files or directories to sample from. Each is visited recursively (directories and, with `--zip`, zip files). Paths are resolved relative to the current directory.

**Options**

- **--output outputdir** (required)  
  Directory where the sample will be written. The directory must not already exist.

- **--dryrun**  
  Do not create any files. Print the path of each file that would be added to the sample (one per line).

- **--exclude pattern** (may be repeated)  
  Regular expression patterns for file and directory **basenames** to ignore. A candidate’s basename must not fully match any exclude pattern. Exclude takes precedence over `--include`.

- **--include pattern** (may be repeated)  
  Regular expression patterns for file **basenames** to include. Only files whose basename fully matches at least one include pattern are candidates. Default is `*` (match all). Directories are traversed regardless of include; they only need to not be excluded.

- **--size** (default)  
  Sample with probability proportional to file size (larger files more likely to be chosen). Mutually exclusive with `--uniform`.

- **--uniform**  
  Sample with uniform probability (each file has the same chance). Mutually exclusive with `--size`.

- **--zip**  
  Treat top-level `.zip` files as containers: list and sample from the files inside them. Zip files inside zips are not opened. Sampled entries are extracted into the output directory.

- **--count n**  
  Number of files to sample. Must be between 1 and 2500. Default is 2500. If there are fewer candidates, all are used.

## Usage and behavior

1. **Stage 1 – Collect candidates**  
   Each given path is visited. Hidden names (basename starting with `.`) and the special directory name `@eaDir` are skipped. Basenames that match any `--exclude` pattern are skipped. Then:
   - **Directories** are recursed into (unless excluded).
   - **Zip files** (with `--zip`) are opened and their member paths are considered; nested zips are ignored.
   - **Regular files** whose basename matches at least one `--include` pattern are added to the candidate list with a weight: file size for `--size`, or 1 for `--uniform`.

2. **Stage 2 – Sample**  
   Up to `--count` candidates are chosen at random without replacement, with selection probability proportional to the weight. The chosen paths are then shuffled.

3. **Stage 3 – Write sample**  
   The output directory is created. For each selected file, an output path is built as:
   - Subdirectory: `00`, `01`, … (25 files per subdir: indices `0..24` → `00`, `25..49` → `01`, etc.).
   - Filename: four-digit index, space, then the file’s basename (e.g. `0000 README.md`).  
   Files on disk are hard-linked into that path when possible; files inside zips are extracted.

## Errors

The program exits with a non-zero status and a message on stderr when:

- **No candidates**: Stage 1 finds no files (e.g. all excluded or paths don’t exist).
- **Output directory exists**: The path given to `--output` already exists.
- **Invalid arguments**: For example `--count` not in 1–2500, or both `--size` and `--uniform` given.

Running `mksample` with no arguments prints usage and option descriptions to stdout.
