# EPS tools

Honda/Acura EPS tooling for openpilot forks: guided firmware flashing, offline
RWD validation, and EPS communication sanity checks.

## Add to your openpilot fork

Copy the complete [`eps_tools/`](eps_tools/) folder into the root of your
openpilot fork, alongside `selfdrive/` and `tools/`, and commit the tooling.
The folder keeps everything needed for the tools together, so contributors can
update it independently of the rest of openpilot.

Once your fork is installed on a comma, launch the recommended guided flasher:

```sh
cd /data/openpilot/eps_tools
python3 flash.py
```

The tools use `panda` and `opendbc` from your openpilot installation. Supply your
own firmware for the exact EPS ECU; this repository contains **no `.rwd` files**.
The [`rwd/`](eps_tools/rwd/) folder is retained for locally supplied images.

See the [installation and usage guide](eps_tools/README.md) for the full workflow,
including the alternative standalone comma installation.

## Tools

| Tool | Purpose |
| --- | --- |
| [`flash.py`](eps_tools/flash.py) | Recommended guided flasher: selection, validation, bus detection, dry run, and explicit flash confirmation. |
| [`eps-diag.py`](eps_tools/eps-diag.py) | Routine EPS communication sanity check; `--recovery` adds troubleshooting guidance. |
| [`check_rwd.py`](eps_tools/check_rwd.py) | Offline container and supported firmware checksum validation. |
| [`eps-update.py`](eps_tools/eps-update.py) | Older manual flashing alternative and the guided flasher's programming backend. |

A successful programming result or communication check does not verify steering
operation. Flashing can damage or permanently brick an EPS ECU. Keep a validated
stock recovery image for your exact ECU; recovery is not guaranteed. Read the
[full guidance and disclaimer](eps_tools/README.md) before flashing.

## Updates and contributions

Submit tooling fixes to this repository. The [contributor guide](eps_tools/CONTRIBUTING.md)
explains importing reviewed updates into a fork and running hardware-free tests.
Firmware images and generated caches are excluded.

Original flashing scripts by mmmorks; current integration and tooling updates by
[RiskyBiscuit-arc](https://github.com/RiskyBiscuit-arc).
See the [license](eps_tools/LICENSE), [source provenance](eps_tools/SOURCE.md),
and retained [rwd-xray license](eps_tools/rwd_xray/LICENSE).
