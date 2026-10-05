# Honda EPS CCP capture

This is the retained CCP dumper used during the Clarity/VFN and CR-V A040 work,
with the CR-V profile and Panda API compatibility fixes. CCP reads firmware via
the comma's Panda. UDS is the separate flashing path; no flashing is needed here.
The current revision has offline regression tests only, not new hardware validation.

## 2021 CR-V, reported 39990-TLA-A220

Matching `39990-TLA` is a reason to try the existing read protocol, not proof of
identical firmware. A220 CCP availability, ROM geometry, controller addresses,
code caves, checksums and patch compatibility remain unverified. Do not use
A040 patch offsets, its RWD, or its bytes to repair an A220 capture.

The optional capture wrapper requests 512 KiB from address zero, based on A040. It uses
CRO `0x727`, discovers the bus/DTO/station, and reads the entire range twice
with separate Panda sessions. It retains each complete read with its SHA-256
in the filename, compares every byte, and writes a content-addressed JSON report.
It tests the two A040-layout application checksum hypotheses and records the
SHA-256 of the candidate `0x4000..0x70000` application slice. Those are explicitly
layout assumptions, not A220 firmware identification or flash authorization.

## Get only the tools onto the comma

SSH into the comma using its existing setup. Only `ccp_honda_eps.py` is needed
for probing and dumping. No branch installation, openpilot rebuild or firmware
update is needed. The Panda library must already be installed on the comma.
Use a new directory; `mkdir` deliberately refuses to mix with a previous download.

```bash
mkdir /data/eps-a220-tools
cd /data/eps-a220-tools
curl -fL -o ccp_honda_eps.py https://raw.githubusercontent.com/RiskyBiscuit-arc/openpilot/eps-crv-a220-dump/eps_tools/ccp_honda_eps.py
```

Confirm the download succeeded before continuing. Use the comma's normal
Python environment; these tools require only its existing Panda package and the
Python standard library. Keep the car parked, ignition ON, engine OFF, wheels
straight. Nobody should need steering assistance during this procedure.
The default transport now uses ELM327 (mode 3, parameter 0), matching the
successful A220 UDS connection. It checks both mode and parameter readback.
`--routing normal` selects ELM327 parameter 1 instead of OBD multiplexing;
use the same setting for probe and capture. `--safety alloutput` retains the
previous transport as an explicit option. Transport changes have offline tests
only; the successful UDS exchange does not prove A220 exposes CCP.

Only CRO `0x727` is attempted by default. No broad active scan is provided.
DTO discovery listens for a response to that targeted request; it does not
require transmitting on every possible CAN ID. Do not substitute VFN's broad
`--scan`, or apply its THR/Odyssey unlock and pointer-window reconstruction to
A220 without establishing that A220 has the same resolver and key algorithm.

```bash
sudo systemctl stop comma
ps -eo args --no-headers | grep -E 'pandad' | grep -v grep | wc -l
```

The process count must be zero. Then:

```bash
cd /data/openpilot
/usr/local/venv/bin/python /data/eps-a220-tools/ccp_honda_eps.py --probe --cro 0x727 --bus 1
```

Run the capture only if the probe shows successful data reads, not merely CONNECT.
The probe's A040 signature address is a diagnostic hint; its absence alone does
not establish that A220 cannot be read. If there is no response or the reads fail,
send the probe output for review; do not flash anything to enable dumping.
If needed, `--sniff --cro 0x727` provides the existing transport diagnostic.
The capture can take several minutes per pass. Keep battery voltage stable.

After successful probe reads, make two fresh captures with the same routing:

```bash
mkdir /data/eps-a220-capture
/usr/local/venv/bin/python /data/eps-a220-tools/ccp_honda_eps.py --dump /data/eps-a220-capture/read-1-DO_NOT_FLASH.bin --cro 0x727 --bus 1 --len 0x80000
/usr/local/venv/bin/python /data/eps-a220-tools/ccp_honda_eps.py --dump /data/eps-a220-capture/read-2-DO_NOT_FLASH.bin --cro 0x727 --bus 1 --len 0x80000
wc -c /data/eps-a220-capture/*.bin
sha256sum /data/eps-a220-capture/*.bin
```

Each completed capture must be 524288 bytes. Matching full hashes establish
repeatability only. Preserve both files, including incomplete or differing ones.
These single-file commands do not generate the optional wrapper's JSON report
or check application checksums; send the raw captures for offline review.

`dump_crv_a220.py` remains optional for automated two-pass capture and reporting.
It needs only itself and the standalone dumper, not `eps_profiles.py`.

On completion, or after interrupting the tool, restore normal operation:

```bash
sudo systemctl start comma
```

The tool attempts to restore Panda SILENT on exit. A USB failure, kill or power
loss can prevent cleanup; it cannot guarantee restoration in those cases.
Confirm normal vehicle/openpilot operation before moving the car.

Send the complete `/data/eps-a220-capture` folder and the probe output, along
with the exact EPS software/part identification and whether its firmware is stock.
The report labels A220 as operator-supplied identity, not an authenticated ECU read.
No VIN is needed. When using the optional wrapper, a nonzero comparison/checksum result means retain and send the
unchanged evidence for review. Existing capture directories/files are refused;
after an interrupted run use a new output directory. Partial files are retained.

## What the result does and does not prove

Matching full reads establish repeatability. They do not rule out a repeatable CCP
read artifact: our earlier A040 capture had a 505-byte artifact at
`0x10A04..0x10BFC` and failed both application checksums. Never flash a raw CCP dump.
This is not an EEPROM/calibration backup or a proven recovery image.

Once the A220 evidence arrives, identify its layout and disassemble the relevant
controller/FF/telemetry paths before deciding whether any A040 changes can port.
No A220 torque, feedforward or telemetry patch is supplied by this branch.

## Other modes and offline checks

`ccp_honda_eps.py --list-profiles` lists existing family assumptions. The generic
`--profile crv` supplies the A040 bus default (0); the A220 wrapper intentionally
does not pin that bus. `--dump` without a profile requests 512 KiB, not an
automatically detected size. `--sram` is separate and unnecessary for this task.

```bash
python3 dump_crv_a220.py --compare first.bin second.bin --out-dir comparison
python3 -m unittest discover -s eps_tools -p test_ccp_honda_eps.py -v
```

The wire operations are CONNECT, SET_MTA, UPLOAD and SHORT_UP. There is no ECU
erase/program/download path. A lost stateful UPLOAD reply is retried only after
resetting MTA, and replies must match the locked DTO bus/ID, counter and length.
Offline tests cover these mechanisms; they do not measure vehicle timing,
interrupt stack behavior, electrical bus behavior or A220 runtime compatibility.
