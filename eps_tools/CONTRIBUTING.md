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
For direct standalone users, clone this repository and use `git pull --ff-only`
to update. Keep your locally supplied firmware under `rwd/`.

## Import into a fork that does not yet have eps_tools/

From the fork root, with a clean working tree:

```sh
git remote add eps-tools https://github.com/RiskyBiscuit-arc/eps-tools.git
git fetch eps-tools main
git subtree add --prefix=eps_tools eps-tools main --squash
```

Then fetch updates with:

```sh
git subtree pull --prefix=eps_tools eps-tools main --squash
```

The subtree pins a reviewed commit; updates are deliberate and committed to your
fork. Resolve any local changes before merging updates.

## Existing forks with a plain eps_tools/ directory

Do not run `subtree add` over an existing directory. Until a deliberate subtree
migration, import a reviewed snapshot instead:

```sh
git remote add eps-tools https://github.com/RiskyBiscuit-arc/eps-tools.git
git fetch eps-tools main
git rev-parse eps-tools/main
git archive eps-tools/main | tar -x -C eps_tools
git diff -- eps_tools
```

Add the remote only once. Record the imported SHA in your commit. An archive
updates files but does not remove retired files: compare `git ls-tree -r
--name-only eps-tools/main` with your local tools and explicitly retire removed
tooling. Preserve local firmware; the remote contains no `.rwd` files.
Stage only the reviewed tooling paths and commit before handing off.

## Validation

Check the production Python-3 scripts and parser for syntax/import errors.
Do not treat the legacy Python-2 reference tools as Python-3 executables.
Hardware changes require explicit bench/vehicle evidence; static checks cannot
validate UDS timing, ECU recovery, or live steering. Do not flash hardware as
part of a contribution check. Do not add firmware files or generated caches.
