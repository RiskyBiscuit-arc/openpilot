#!/usr/bin/env python3
"""
ccp_honda_eps.py — CCP ROM dumper for Honda/Acura SH72A0-family EPS, over CAN.

Runs ON THE COMMA (ssh in, run it there). Self-contained: only needs the openpilot
`panda` library already on the device. Read-only. Intended for SH72A0 EPS units that
expose CCP. CRO/DTO/bus/station are auto-discovered; geometry comes from
`eps_profiles.py` via --profile. Earlier versions were used on Clarity and CR-V
A040; a retained A040 dump had a read artifact. This revision has offline tests
only. A220 CCP availability and layout remain unverified.

Known configs (the sweep AUTO-DISCOVERS these — override only if you want to pin one):
    Clarity (39990-TRW):  CRO 0x727 / DTO 0x728, bus 0,  ~384 KB
    Civic   (39990-TBA):  CRO 0x727 / DTO 0x728, bus 1,  ~512 KB
    CR-V    (39990-TLA):  CRO 0x727 / DTO 0x728,         ~512 KB (A040)
    RDX     (39990-TJB):  CRO 0x727? (0x646 fallback),  bus 1?, 512 KB
The DTO is always auto-discovered (some custom firmwares move it), so you never
have to know it up front.

Protocol (CCP / CAN Calibration Protocol), keyless reads:
    CONNECT(01) -> SET_MTA(02,addr) -> UPLOAD(04,n) | SHORT_UP(0F,addr,n).
    CONNECT station is 0x0000 (wildcard) or 0x1117 — both family-accepted.
    READ-ONLY: only 01/02/04/0F are ever sent. DNLOAD/PROGRAM are not implemented.

The four things that make it reliable (learned the hard way on the Clarity):
  1. STOP openpilot first so this process owns Panda. The default is ELM327 with
     OBD routing, matching eps-update.py. Mode AND parameter must read back correctly.
         sudo systemctl stop comma        # AGNOS oneshot service; stays stopped
         ps -eo args --no-headers | grep -E 'pandad' | grep -v grep | wc -l
  2. Drain the RX buffer before each send — the car bus is a ~3000 fps firehose and
     one can_recv() doesn't empty it, so the reply is lost in the overflow.
  3. Match the reply by CONTENT: a CRM is `FF 00 <ctr> ...`. Matching byte[0]==0xFF
     & byte[1]==0x00 & byte[2]==<the counter we sent> isolates it from periodic
     traffic even when a custom build parks telemetry on the DTO id.
  4. SHORT_UP (0x0F) is stateless (addr in the command) so a lost frame retries with
     no MTA drift. Fallback UPLOAD retries must reset MTA before each attempt.

SAFETY: This is live STEERING firmware. READ-ONLY. Car PARKED, ignition ON / engine
OFF, wheels straight. ELM327 permits diagnostic IDs; optional ALLOUTPUT disables
TX filtering. Both modes are for this parked procedure only.
On exit, SILENT restoration is attempted; device/power failures can prevent it.

USAGE (on the comma, after `sudo systemctl stop comma`):
    python3 ccp_honda_eps.py --sniff                 # full diagnostic (run this if unsure)
    python3 ccp_honda_eps.py --probe                 # find CRO/DTO/bus, confirm reads
    python3 ccp_honda_eps.py --dump eps.bin          # requests 512 KB; size is not detected
    python3 ccp_honda_eps.py --dump eps.bin --profile crv     # geometry from profile
    python3 ccp_honda_eps.py --dump eps.bin --bus 0 --cro 0x727 --len 0x60000
    python3 ccp_honda_eps.py --sram eps_sram.bin     # 64 KB SRAM @0xFFF80000
Existing output files are refused. Use a fresh path for every capture.
Raw CCP dumps are analysis evidence, NEVER flash inputs. A220 is unverified.
"""
import argparse, os, sys, time

for _p in ("/data/openpilot", "/data/pythonpath"):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
# Informational flags must work off-comma, before the panda dependency is needed.
if "--list-profiles" in sys.argv:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import eps_profiles as _ep
    for _prof in _ep.PROFILES:
        print(_prof.describe())
    sys.exit(0)

try:
    from panda import Panda
except ImportError:
    Panda = None


def _safety_mode(attr, enum_name, fallback):
    """Portable across panda versions: upstream exposes Panda.SAFETY_*, newer forks
    use the cereal CarParams.SafetyModel enum. allOutput=17/silent=0 are stable."""
    v = getattr(Panda, attr, None)
    if v is not None:
        return int(v)
    for mod in ("opendbc.car.structs", "cereal.car"):
        try:
            CarParams = __import__(mod, fromlist=["CarParams"]).CarParams
            return int(getattr(CarParams.SafetyModel, enum_name))
        except Exception:  # noqa: BLE001
            continue
    return fallback


ALLOUTPUT = _safety_mode("SAFETY_ALLOUTPUT", "allOutput", 17)
SILENT    = _safety_mode("SAFETY_SILENT",    "silent",    0)
ELM327    = _safety_mode("SAFETY_ELM327",    "elm327",    3)

# ---------------- Honda EPS CCP config ----------------
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import eps_profiles

CRO_TRY   = [0x0727]                    # targeted family candidate; no guessed VSA-range fallback
BUSES_TRY = [0, 1, 2]                   # Clarity=0, Civic/RDX=1; sweep all
STATIONS  = [0x0000, 0x1117]            # both family-accepted CONNECT stations
USER_MAT  = (0x00000000, 0x00080000)   # A040 geometry; other revisions unverified
SRAM      = (0xFFF80000, 0x00010000)   # 64 KB on-chip RAM
CHUNK = 5                              # bytes per read (max per CCP DTO frame)

C_CONNECT, C_SET_MTA, C_UPLOAD, C_SHORT_UP = 0x01, 0x02, 0x04, 0x0F


class CCP:
    def __init__(self, bus, cro_try=None, stations=None, verbose=True,
                 safety="elm327", routing="obd"):
        if Panda is None:
            raise RuntimeError("Could not import Panda. Run on the comma with its openpilot Python environment.")
        self.bus = bus
        self.cro_try = cro_try or CRO_TRY
        self.stations = stations or STATIONS
        self.verbose = verbose
        self.ctr = 0
        self.dto = None            # locked after discovery; None = accept any id
        self.dto_bus = None        # bus the reply actually came back on (may differ)
        self.cro = self.cro_try[0] # locked after discovery to whichever CRO answers
        self.use_short = True
        self.safety_mode = ELM327 if safety == "elm327" else ALLOUTPUT
        self.safety_param = int(routing == "normal") if safety == "elm327" else 0
        self.closed = False
        self.p = Panda()
        try:
            self.p.set_safety_mode(self.safety_mode, self.safety_param)
            self._assert_safety()
            print(f"[transport] {safety} mode={self.safety_mode} param={self.safety_param} "
                  f"routing={routing if safety == 'elm327' else 'normal'}")
            self.p.can_clear(0xFFFF)
        except BaseException:
            self.close()
            raise

    def _assert_safety(self):
        time.sleep(0.15)
        try:
            health = self.p.health()
            mode = health.get("safety_mode")
            param = health.get("safety_param")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("Cannot verify Panda safety mode") from exc
        if mode != self.safety_mode or param != self.safety_param:
            raise SystemExit(
                f"\n*** ABORT: requested Panda mode/param {self.safety_mode}/{self.safety_param}, "
                f"read back {mode}/{param}. No CCP request sent.\n"
                f"    Possible causes include another Panda owner or incompatible firmware/API.\n"
                f"    This is not proof that pandad is running. First confirm openpilot is stopped:\n"
                f"        sudo systemctl stop comma\n"
                f"        ps -eo args --no-headers | grep -E 'pandad' | grep -v grep | wc -l\n")

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.p.set_safety_mode(SILENT)
            time.sleep(0.15)
            if self.p.health().get("safety_mode") != SILENT:
                raise RuntimeError("SILENT did not stick in health readback")
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: could not restore Panda SILENT: {exc}", file=sys.stderr)
        finally:
            try:
                self.p.close()
            except Exception as exc:  # noqa: BLE001
                print(f"WARNING: could not close Panda: {exc}", file=sys.stderr)

    def _next_ctr(self):
        self.ctr = (self.ctr + 1) & 0xFF
        return self.ctr

    def _drain(self, maxit=1000):
        for _ in range(maxit):
            if not self.p.can_recv():
                return

    def xfer(self, body, timeout=0.06, retries=6, reply_size=3):
        """Send CRO on self.bus (we own byte[1]=counter), drain first, then spin-recv
        for the matching CRM `FF 00 <ctr> ...`. Returns (dto_id, dto_bus, frame) or
        (None, None, None).

        The reply is identified purely by CONTENT (FF 00 + a counter we just sent), so
        we accept it on ANY bus — the EPS may answer on a different bus than the CRO
        went out on (gateway/forwarding). We only skip our own TX echo. We also match
        any counter sent within this call, so a slightly-late reply isn't lost."""
        sent = set()
        for _ in range(retries):
            c = self._next_ctr(); sent.add(c)
            frame = bytearray((bytes(body) + b"\x00" * 8)[:8])
            frame[1] = c
            self._drain()
            self.p.can_send(self.cro, bytes(frame), self.bus)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for msg in self.p.can_recv():
                    addr, dat, src = _unpack(msg)
                    if src & 0x80:                 # skip our own TX echo; accept any bus
                        continue
                    if len(dat) >= reply_size and dat[0] == 0xFF and dat[1] == 0x00 and dat[2] in sent:
                        if (self.dto is None or addr == self.dto) and (self.dto_bus is None or src == self.dto_bus):
                            return addr, (src & 0x7F), bytes(dat)
        return None, None, None

    def connect(self):
        """CONNECT and auto-discover CRO + DTO + station. Sweeps candidate CROs and
        both accepted stations; locks self.cro + self.dto on the first reply."""
        self.dto = None
        self.dto_bus = None
        for cro in self.cro_try:
            self.cro = cro
            for station in self.stations:
                addr, dbus, _ = self.xfer([C_CONNECT, 0, station & 0xFF, (station >> 8) & 0xFF], retries=4)
                if addr is not None:
                    self.dto = addr
                    self.dto_bus = dbus
                    if self.verbose:
                        xb = f" (reply on bus {dbus}!)" if dbus != self.bus else ""
                        print(f"  bus {self.bus}: CONNECT (CRO {cro:#06x}, station {station:#06x}) "
                              f"-> CRM on {addr:#06x}{xb}  [locked CRO={cro:#06x} DTO={addr:#06x}]")
                    return True
        self.cro = self.cro_try[0]
        if self.verbose:
            print(f"  bus {self.bus}: CONNECT -> no reply "
                  f"(CROs {[hex(x) for x in self.cro_try]}, stations {[hex(x) for x in self.stations]})")
        return False

    def short_up(self, addr, n=CHUNK):
        _, _, r = self.xfer([C_SHORT_UP, 0, n, 0x00] + list(addr.to_bytes(4, "big")), reply_size=3 + n)
        return r[3:3 + n] if r else None

    def set_mta(self, addr):
        _, _, r = self.xfer([C_SET_MTA, 0, 0x00, 0x00] + list(addr.to_bytes(4, "big")))
        return r is not None

    def upload(self, n=CHUNK):
        # UPLOAD advances MTA even if its reply is lost. Never retry it alone.
        _, _, r = self.xfer([C_UPLOAD, 0, n], retries=1, reply_size=3 + n)
        return r[3:3 + n] if r else None

    def read(self, addr, n=CHUNK):
        if self.use_short:
            v = self.short_up(addr, n)
            if v is not None:
                return v
        return self.read_at(addr, n)

    def read_at(self, addr, n=CHUNK):
        for _ in range(6):
            if self.set_mta(addr):
                data = self.upload(n)
                if data is not None:
                    return data
        return None


def _unpack(msg):
    if len(msg) == 4:
        addr, _bt, dat, src = msg
    else:
        addr, dat, src = msg[0], msg[-2], msg[-1]
    return addr, bytes(dat), int(src)


def _hondaish(v4):
    """Heuristic: a real SH72A0 reset vector is 0x000008xx (initial PC in low flash)."""
    return v4 is not None and v4[:2] == b"\x00\x00" and v4[2] == 0x08


# ---------------- modes ----------------
def do_probe(buses, cro_try, stations, **transport):
    print(f"[probe] CCP sweep — CROs {[hex(x) for x in cro_try]}, stations "
          f"{[hex(x) for x in stations]}, DTO auto-discover")
    for bus in buses:
        c = CCP(bus, cro_try, stations, **transport)
        try:
            if not c.connect():
                c.close(); continue
            v0 = c.short_up(0x00000000, 5)
            if v0 is None:
                c.use_short = False
                v0 = c.read_at(0x00000000, 5)
                print(f"  bus {bus}: SHORT_UP unsupported -> using SET_MTA+UPLOAD")
            sig = c.read(0x00002D9C, 5)   # SH72A0_CCP string on this family
            tag = "  <-- 'SH72A' CCP signature, read path CONFIRMED" if sig and sig[:5] == b"SH72A" else ""
            rv = "  <-- valid reset vector" if _hondaish(v0[:4] if v0 else None) else ""
            print(f"  bus {bus}: CRO={c.cro:#06x} DTO={c.dto:#06x}  "
                  f"read@0x0={v0[:4].hex() if v0 else '----'}{rv}  @0x2d9c={sig.hex() if sig else '----'}{tag}")
            # flash-extent landmarks so you know the size to dump
            print("  flash extent:", end=" ")
            for a in (0x40000, 0x50000, 0x5FFF0, 0x60000, 0x7FFF0):
                v = c.read(a, 4)
                st = "no-reply" if v is None else ("FF" if v == b"\xff" * 4 else "data")
                print(f"{a:#08x}={st}", end="  ")
            print()
            print(f"\n  ==> LIVE on bus {bus}, CRO {c.cro:#06x}, DTO {c.dto:#06x}. Dump:\n"
                  f"      python3 {sys.argv[0]} --dump eps.bin --bus {bus} --cro {c.cro:#x} "
                  f"--safety {transport.get('safety', 'elm327')} --routing {transport.get('routing', 'obd')}")
            return 0
        finally:
            c.close()
    print("  no CONNECT on any bus. openpilot stopped? ignition ON? (try --sniff)")
    return 1


def do_sniff(buses, cro_try, stations, **transport):
    """FULL one-shot diagnostic — a single run answers: live bus? EPS present? CRO
    reaching the wire? anything answering? on which CRO/DTO/bus?"""
    print("[sniff] FULL diagnostic — isolates ignition/harness vs bus routing vs silent EPS")
    c = CCP(buses[0] if buses else 0, cro_try, stations, verbose=False, **transport)
    p = c.p
    try:
        h = p.health()
        print("\n  --- panda health ---")
        for k in ("safety_mode", "ignition_line", "ignition_can", "car_harness_status",
                  "controls_allowed", "voltage", "rx_buffer_overflow", "safety_tx_blocked"):
            print(f"      {k:<20}= {h.get(k)}")
        print(f"      need: safety_mode == {c.safety_mode}, safety_param == {c.safety_param}, ignition ON")

        p.can_clear(0xFFFF)
        t0 = time.time(); by = {}
        while time.time() - t0 < 2.0:
            for m in p.can_recv():
                a, d, s = _unpack(m)
                if s & 0x80:
                    continue
                by.setdefault(s & 0x7F, {}).setdefault(a, 0)
                by[s & 0x7F][a] += 1
        tot = sum(sum(v.values()) for v in by.values())
        print(f"\n  --- passive scan 2.0s: {tot} frames on {len(by)} bus(es) ---")
        if tot == 0:
            print("      *** ZERO frames — panda not on a live car bus. Ignition ON (engine off ok)?")
            print("          Harness seated? CCP cannot work until this is nonzero.")
        for bus in sorted(by):
            ids = sorted(by[bus]); n = sum(by[bus].values())
            std = [hex(x) for x in ids if x <= 0x7FF]
            ext = [hex(x) for x in ids if x > 0x7FF]
            diag = [hex(x) for x in ids if 0x600 <= x <= 0x7FF]
            print(f"      bus {bus}: {n} frames, {len(ids)} unique ids")
            print(f"         std ids (<=0x7FF): {std}")
            if ext:
                print(f"         29-bit ids (UDS?): {ext}")
            print(f"         DIAG range 0x600-0x7FF: {diag if diag else 'NONE'}")

        print(f"\n  --- active CONNECT (CROs {[hex(x) for x in cro_try]}, stations "
              f"{[hex(x) for x in stations]}) ---")
        for bus in buses:
            for cro in cro_try:
                for station in stations:
                    p.can_clear(0xFFFF); p.can_recv()
                    echo = False; crm = {}; diag = {}
                    for k in range(6):
                        fr = bytes([0x01, 0xA0 + k, station & 0xFF, (station >> 8) & 0xFF, 0, 0, 0, 0])
                        p.can_send(cro, fr, bus)
                        t0 = time.time()
                        while time.time() - t0 < 0.10:
                            for m in p.can_recv():
                                a, d, s = _unpack(m)
                                if s & 0x80:
                                    if a == cro:
                                        echo = True
                                    continue
                                # a REAL CCP CRM is `FF 00 <our counter>`; requiring byte[1]==0
                                # and the exact counter rejects normal FF-leading status frames.
                                if len(d) >= 3 and d[0] == 0xFF and d[1] == 0x00 and 0xA0 <= d[2] <= 0xA5:
                                    crm[hex(a)] = d.hex()
                                elif 0x600 <= a <= 0x7FF:
                                    diag[hex(a)] = d.hex()   # diag-range frame (informational only)
                    et = "YES" if echo else "NO <- CRO not reaching the wire!"
                    extra = f"  diag-range-seen={diag}" if diag else ""
                    print(f"      bus {bus} CRO {cro:#06x} station {station:#06x}: "
                          f"TX-echo={et}  CCP-reply={crm if crm else 'none'}{extra}")
    finally:
        c.close()
    print("\n  === how to read this ===")
    print("   * ZERO passive frames                 -> ignition/harness; fix first.")
    print("   * frames present, TX-echo=NO          -> CRO not leaving the panda (panda/routing).")
    print("   * TX-echo=YES, candidates=none on all  -> EPS present but silent to these CROs;")
    print("                                            look at the DIAG-range ids for the real CRO.")
    print("   * any 'candidates' printed             -> CCP answering; that CRO+id are the transport.")
    return 0


def do_dump(start, length, outpath, buses, cro_try, stations, **transport):
    os.makedirs(os.path.dirname(os.path.abspath(outpath)) or ".", exist_ok=True)
    if start < 0 or length <= 0 or start + length > 0x100000000:
        raise ValueError("Invalid 32-bit read range")
    if os.path.exists(outpath):
        raise FileExistsError(f"Refusing to append to or overwrite {outpath}; choose a fresh path")
    resume = 0
    for bus in buses:
        c = CCP(bus, cro_try, stations, **transport)
        f = None
        try:
            if not c.connect():
                c.close(); continue
            if c.short_up(start + resume, 1) is None:
                c.use_short = False
                print(f"  bus {bus}: SHORT_UP unsupported -> SET_MTA+UPLOAD (slower)")
            print(f"[dump] bus {bus}: {start:#010x}..{start+length:#010x} ({length} bytes), "
                  f"CRO={c.cro:#06x} DTO={c.dto:#06x}, {'SHORT_UP' if c.use_short else 'UPLOAD'}")
            f = open(outpath, "xb")
            t0 = time.time(); n = resume; misses = 0
            while n < length:
                want = min(CHUNK, length - n)
                got = c.read(start + n, want)
                if got is None or len(got) < want:
                    misses += 1
                    if misses >= 20 or not c.connect():
                        print(f"\n  STALLED @ {start+n:#010x} — partial evidence retained; use a fresh output path.")
                        f.close(); c.close(); return 1
                    continue
                f.write(got[:want]); n += want
                if n % 8192 < CHUNK:
                    f.flush()
                    r = (n - resume) / max(time.time() - t0, 1e-3)
                    print(f"  {n}/{length} ({100*n//length}%)  {r:.0f} B/s  "
                          f"eta {(length-n)/max(r,1):.0f}s  misses={misses}", flush=True)
            f.close()
            print(f"\n[done] wrote {n} bytes -> {outpath}  ({misses} retries)")
            return 0
        finally:
            if f is not None:
                f.close()
            c.close()
    print("no CONNECT on any bus — nothing dumped.")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--sniff", action="store_true")
    ap.add_argument("--dump", metavar="OUT")
    ap.add_argument("--sram", metavar="OUT")
    ap.add_argument("--bus", type=int, default=None)
    ap.add_argument("--safety", choices=("elm327", "alloutput"), default="elm327")
    ap.add_argument("--routing", choices=("obd", "normal"), default="obd",
                    help="ELM327 bus routing: obd matches eps-update.py; normal uses param 1")
    ap.add_argument("--cro", type=lambda x: int(x, 0), default=None, help="pin a single CRO id")
    ap.add_argument("--station", type=lambda x: int(x, 0), default=None, help="pin a single CONNECT station")
    ap.add_argument("--start", type=lambda x: int(x, 0), default=None)
    ap.add_argument("--len", dest="length", type=lambda x: int(x, 0), default=None)
    ap.add_argument("--profile", default=None, choices=eps_profiles.keys(),
                    help="EPS variant; supplies default --bus and --len (see eps_profiles.py)")
    ap.add_argument("--list-profiles", action="store_true",
                    help="print the known EPS variants and exit")
    a = ap.parse_args()
    transport = {"safety": a.safety, "routing": a.routing}

    if getattr(a, "list_profiles", False):
        for _p in eps_profiles.PROFILES:
            print(_p.describe())
        return 0
    if a.profile:
        _p = eps_profiles.by_key(a.profile)
        if a.bus is None:
            a.bus = _p.ccp_bus
        if a.length is None:
            a.length = _p.mat_size
        print("[profile] %s: bus %s, dump length 0x%X%s"
              % (_p.key, a.bus, a.length, "" if _p.verified else "  (UNVERIFIED profile)"))
    buses = [a.bus] if a.bus is not None else BUSES_TRY
    cro_try = [a.cro] if a.cro is not None else CRO_TRY
    stations = [a.station] if a.station is not None else STATIONS

    print("=" * 66)
    print(" Honda/Acura SH72A0 EPS CCP dump — READ-ONLY. Car PARKED, ignition ON,")
    print(" openpilot STOPPED (sudo systemctl stop comma). SILENT attempted on exit.")
    print("=" * 66)
    try:
        if a.probe: return do_probe(buses, cro_try, stations, **transport)
        if a.sniff: return do_sniff(buses, cro_try, stations, **transport)
        if a.sram:  return do_dump(*SRAM, a.sram, buses, cro_try, stations, **transport)
        if a.dump:
            start = a.start if a.start is not None else USER_MAT[0]
            length = a.length if a.length is not None else USER_MAT[1]
            return do_dump(start, length, a.dump, buses, cro_try, stations, **transport)
    except KeyboardInterrupt:
        print("\n[abort] interrupted — check above for any SILENT restoration warning.")
        return 130
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
