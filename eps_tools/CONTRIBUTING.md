# Contributing and updates

The canonical source is https://github.com/RiskyBiscuit-arc/eps-tools.
Submit tooling fixes there. This openpilot fork retains its existing firmware
files; the standalone repository has no firmware in its initial commit or history.
`rwd_format/` is the Python-3 parser. `rwd_xray/format/` is reference-only
upstream code; preserve its MIT license and attribution.

## Setup

Use Python 3.9 or newer. Offline `check_rwd.py` and `rwd_format/` use the standard
library. Flashing and diagnostics also need `panda`, `opendbc`, and `tqdm` from a
compatible openpilot installation. This repository does not install or replace
those dependencies. Run scripts from the tools directory with the installation
on `PYTHONPATH`, for example `PYTHONPATH=/data/openpilot python3 flash.py`.
`flash.py` is the recommended flasher; `eps-update.py` is the older manual
alternative and the guided script's programming backend. `eps-diag.py` normally
checks communication; use `--recovery` to request troubleshooting guidance.

For direct standalone users, clone this repository and use `git pull --ff-only`
to update. Then `cd eps_tools` to run scripts. Keep your locally supplied
firmware under `eps_tools/rwd/` in the clone.

## Drop into openpilot or update an existing fork

Every distributed file lives under `eps_tools/` in the standalone repository.
The primary installation is to copy that folder into your openpilot fork root
and commit the tooling there. On the comma it then lives at
`/data/openpilot/eps_tools/`. `/data/media/0/eps_tools/` is an alternative for
standalone device copies, not the fork integration location.

For a Git-based snapshot import,
run from the openpilot root with a clean working tree:

```sh
git remote add eps-tools https://github.com/RiskyBiscuit-arc/eps-tools.git
git fetch eps-tools main
git rev-parse eps-tools/main
git archive eps-tools/main eps_tools | tar -x -C .
git diff -- eps_tools
```

Add the remote only once. Record the imported SHA in your commit. The archive
already contains the `eps_tools/` prefix: extracting into `eps_tools/` would
incorrectly create `eps_tools/eps_tools/`.

An archive updates files but does not remove retired files: compare
`git ls-tree -r --name-only eps-tools/main -- eps_tools/` with your local tools
and explicitly retire removed tooling. Preserve local firmware; the remote
contains no `.rwd` files. Review conflicts with any local edits before importing.
Stage only the reviewed tooling paths and commit before handing off.

The repository no longer has scripts at its root. The former direct
`git subtree add/pull --prefix=eps_tools ... main` instructions are superseded;
using them with this layout would produce an extra nested folder. Use the
snapshot import above.

## Validation

Check the production Python-3 scripts and parser for syntax/import errors.
Do not treat the legacy Python-2 reference tools as Python-3 executables.
Hardware changes require explicit bench/vehicle evidence; static checks cannot
validate UDS timing, ECU recovery, or live steering. Do not flash hardware as
part of a contribution check. Do not add firmware files or generated caches.

Run the hardware-free regression suite from the openpilot or standalone repo root:

```sh
python3 -m unittest discover -s eps_tools/tests -v
```

Tests use synthetic containers and fake transports, never firmware downloads or
live Panda access. Optimized-Python validation is covered in subprocesses.
