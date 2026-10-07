# EPS tools

Canonical tooling repository: [RiskyBiscuit-arc/eps-tools](https://github.com/RiskyBiscuit-arc/eps-tools).
See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and fork updates.
The standalone repository keeps `rwd/` but distributes no firmware images.

Standalone tooling for reading, validating, and flashing Honda/Acura EPS
firmware (`.rwd`). Works on the current opendbc layout — no panda-submodule or
`selfdrive.car` dependencies.

Credit to mmmorks for the original flasher scripts, and to
[RiskyBiscuit-arc](https://github.com/RiskyBiscuit-arc) for updating them to the
current opendbc layout and adding the safety checks.

> **Disclaimer:** Flashing EPS firmware can damage or permanently brick your
> power-steering ECU. **You alone are responsible for your EPS and your vehicle,
> and you use these tools entirely at your own risk** — no warranty of any kind,
> express or implied. Always validate the image (`check_rwd.py`) and do a dry run
> before flashing.

```
eps_tools/
  flash.py          recommended guided flasher (selection, validation, bus detection)
  eps-update.py     older manual alternative; also used internally by flash.py
  check_rwd.py      offline .rwd checksum validator (stdlib only)
  eps-diag.py       EPS CAN liveness/diagnostic (sniff, UDS ping, part number)
  rwd_format/       vendored Python-3 .rwd container parser (0x5A/0x31)
  rwd_xray/         cfranyota/rwd-xray @ 8d8e1ff (MIT), reference copy: eps_tool.py patch offsets and
                    table values per EPS, table/checksum search tools. Its format/ is the Python-2 original
                    of rwd_format/, which is the one to run.
  rwd/              local firmware images (not distributed by eps-tools)
```

Run the scripts **from this folder** so `rwd_format` resolves; `opendbc`/`panda`
come from the openpilot install (prefix with `PYTHONPATH=/data/openpilot` if you
hit import errors).

## Add to your openpilot fork (primary use)

Copy the complete `eps_tools/` folder from this repository into the root of your
openpilot fork, alongside `selfdrive/` and `tools/`, and commit the tooling to
your fork. See [CONTRIBUTING.md](CONTRIBUTING.md) for importing future updates.
The tools need the fork's `panda` and `opendbc` dependencies.

Once your fork is installed on a comma, the tools are at
`/data/openpilot/eps_tools/`. Run the recommended guided flasher there:

```sh
cd /data/openpilot/eps_tools
PYTHONPATH=/data/openpilot python3 flash.py
```

## Alternative: standalone copy on a comma

If you want to use the tools without adding them to your fork, copy `eps_tools/`
to the comma. A manually dropped `/data/openpilot/eps_tools/` folder can be used,
but it is untracked and can be removed by openpilot updates. For a standalone
copy you want to keep across updates, use `/data/media/0/eps_tools/` instead:

```sh
cd /data/media/0/eps_tools
PYTHONPATH=/data/openpilot python3 flash.py
```

This alternative still uses the installed openpilot dependencies. The media
location is for standalone copies; it is not where you add the tools to a fork.

## Recommended flasher: flash.py

Supply a firmware image for your exact ECU under `rwd/`; firmware is not included
in the standalone repository. Keep a validated matching stock recovery image.
Run `python3 flash.py` from the tools folder for whichever installation above
you use.

The guided script lists compatible images when the cached car identification is
available, checks the selected image, prompts you to turn the car OFF, and stops
openpilot. It then prompts for ignition ON (engine OFF), detects the CAN bus,
offers the recommended dry run, and requires you to type `FLASH` before programming.
Follow the prompts; do not bypass image validation or the dry run for normal use.

After **“Firmware programming completed”**, the optional communication sanity
check can confirm that the EPS responds. It does not mean a failure was detected,
and it does not verify steering operation or firmware correctness. The final menu
also offers to restore openpilot or reboot. A failed programming attempt is clearly
reported and has a separate retry/recovery flow; recovery is not guaranteed.

## Older alternative: eps-update.py

`eps-update.py` is the older manual interface and remains the programming backend
used by `flash.py`. Prefer the guided script. For manual use, stop openpilot with
the car OFF (`sudo systemctl stop comma`, then `tmux kill-session -t comma`),
then turn ignition ON with the engine OFF. Select the correct CAN bus explicitly.
From your installed `eps_tools/` folder:

```sh
# Dry run: stops before erase/programming.
PYTHONPATH=/data/openpilot python3 eps-update.py rwd/YOUR_FIRMWARE.rwd -b 1
# Actual programming: explicit --danger is required.
PYTHONPATH=/data/openpilot python3 eps-update.py rwd/YOUR_FIRMWARE.rwd -b 1 --danger
```

An expected dry-run stop is printed without a traceback. Bus 1 is the manual
default, not a guarantee that it is correct for your vehicle. Restore openpilot
when finished, or reboot the device.

### `--skip-checksum` (not recommended)
If a firmware isn't covered by the checksum checker, you can add `--skip-checksum`.
**Be careful — flashing a `.rwd` with invalid checksums can brick the EPS.** Only
use it on an image you trust.
```
python3 eps-update.py rwd/SOME_FIRMWARE.rwd -b 1 --skip-checksum --danger
```

## Optional EPS communication sanity check

With ignition ON and openpilot stopped so the Panda is available:

```sh
PYTHONPATH=/data/openpilot python3 eps-diag.py
# Pin the bus/address if known:
PYTHONPATH=/data/openpilot python3 eps-diag.py -b 1 --addr 0x18DA30F1
# Add troubleshooting guidance only when investigating a failed flash:
PYTHONPATH=/data/openpilot python3 eps-diag.py -b 1 --recovery
```

Normal results are **communication confirmed**, **communication not confirmed**,
or **check could not run**. Negative UDS responses still confirm communication;
unsupported sessions and unreadable software IDs are reported separately.
Passive silence at the diagnostic response address is inconclusive, not proof of
a dead ECU. Cached CarParams identifiers are labeled and cannot confirm current
firmware. No communication result proves steering operation or diagnoses a brick.

Exit codes are 0 for confirmed communication, 1 for unconfirmed communication,
and 2 for setup/runtime failure. `--sniff-only` returns 1 when no response frames
are observed. `--scan` returns 0 when any scanned ECU responds, which does not
specifically confirm the EPS. Cleanup warnings do not replace the check result.

## If a flash fails / crashes
A failure after erase can leave the EPS without power-steering assist. Recovery
is not guaranteed. Retain a verified stock recovery image for your exact ECU;
inspect the failure before retrying. The guided `flash.py` provides a recovery menu.

Tooling committed to your fork belongs under `/data/openpilot/eps_tools/`.
Manually copied tools and locally supplied firmware there may be untracked and
removed by an update. Keep recovery firmware outside the updater-managed tree,
and do not run an openpilot update during flashing. For standalone tools, the
alternative media location above keeps the copy outside that tree.

## Validate an image offline
```
python3 check_rwd.py rwd/39990-TLA-A040-linear-max.rwd
python3 check_rwd.py rwd/*.rwd
```

Unsupported checksum coverage is reported as not fully validated and returns a
nonzero exit status, as do malformed images and failed checksums. The explicit
`--skip-checksum` flow can bypass firmware checksum checks, but cannot bypass
container structure, declared payload length, or the file checksum.

See `rwd/README.md` for local firmware handling. Firmware is excluded from the
standalone tools repository.
