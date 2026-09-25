#!/usr/bin/env python3
"""
eps_profiles.py — Honda SH-2A EPS variant profiles.

Single place where vehicle/part assumptions live. The UART dump/flash tools and
the CCP dump tool all resolve geometry through here, so no tool carries a
hardcoded vehicle layout of its own.

Geometry facts that hold across every known Honda SH-2A EPS:

  * the application starts at 0x4000 inside the user MAT
  * the two embedded firmware checksum words sit at the TOP of the application
    payload: `app_size - 0x80` (plain sum) and `app_size - 0x02` (negated sum)

That derivation reproduces the previously hardcoded tables exactly:
  Clarity app 0x4C000 -> 0x4BF80 / 0x4BFFE
  CR-V    app 0x6C000 -> 0x6BF80 / 0x6BFFE

VERIFIED vs INFERRED
  Only `clarity` and `crv` have been confirmed against real images/hardware.
  The others are inferred from part-number/size reports and are marked
  `verified=False`. Tools must refuse to WRITE an unverified profile.

  To verify one, use the porting kit in `porting/`: inspect the container,
  derive its cipher, locate its tables and checksum words, then fill in the
  real geometry here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

APP_START = 0x4000              # application offset inside the user MAT
SUM_FROM_TOP = 0x80             # plain-sum checksum word, from top of payload
NEGSUM_FROM_TOP = 0x02          # negated-sum checksum word, from top of payload


@dataclass(frozen=True)
class EpsProfile:
    key: str
    name: str
    part_prefixes: tuple
    mat_size: int                       # full user MAT on the chip
    app_size: int                       # application payload length
    app_start: int = APP_START
    ccp_bus: int = 0                    # bus the CCP CRO/DTO answers on
    verified: bool = False              # confirmed against a real image/unit?
    notes: str = ""

    @property
    def app_end(self) -> int:
        return self.app_start + self.app_size

    @property
    def checksum_offsets(self) -> tuple:
        """App-relative embedded checksum words as (kind, offset).

        kind 0 = sum of big-endian u16; kind 1 = sum of negated big-endian u16.
        """
        return (
            (0, self.app_size - SUM_FROM_TOP),
            (1, self.app_size - NEGSUM_FROM_TOP),
        )

    def describe(self) -> str:
        mark = "verified" if self.verified else "INFERRED — do not write"
        return (
            f"{self.key:8s} {self.name:22s} part {'/'.join(self.part_prefixes):12s} "
            f"MAT 0x{self.mat_size:X}  app 0x{self.app_start:X}+0x{self.app_size:X}  [{mark}]"
        )


PROFILES = (
    EpsProfile(
        key="clarity", name="Honda Clarity", part_prefixes=("39990-TRW",),
        mat_size=0x60000, app_size=0x4C000, ccp_bus=0, verified=True,
        notes="Original target of this tool; 384 KB MAT.",
    ),
    EpsProfile(
        key="crv", name="Honda CR-V 5G / Accord", part_prefixes=("39990-TLA",),
        mat_size=0x80000, app_size=0x6C000, ccp_bus=0, verified=True,
        notes="R5F72A08/SH72A0, 512 KB MAT. Confirmed against 39990-TLA-A040.",
    ),
    EpsProfile(
        key="civic", name="Honda Civic", part_prefixes=("39990-TBA",),
        mat_size=0x80000, app_size=0x6C000, ccp_bus=1, verified=False,
        notes="512 KB reported; layout assumed identical to CR-V. UNCONFIRMED.",
    ),
    EpsProfile(
        key="rdx", name="Acura RDX", part_prefixes=("39990-TJB",),
        mat_size=0x80000, app_size=0x6C000, ccp_bus=1, verified=False,
        notes="512 KB reported; CRO may be 0x646. UNCONFIRMED.",
    ),
)

_BY_KEY = {p.key: p for p in PROFILES}


def keys() -> list:
    return [p.key for p in PROFILES]


def by_key(key: str) -> EpsProfile:
    try:
        return _BY_KEY[key.lower()]
    except KeyError:
        raise RuntimeError(
            f"unknown profile {key!r}; known: {', '.join(keys())}"
        ) from None


def by_part_number(part: str):
    """Resolve a profile from a part number such as '39990-TLA-A040'."""
    up = part.upper().replace(",", "-")
    for p in PROFILES:
        if any(up.startswith(prefix) for prefix in p.part_prefixes):
            return p
    return None


def candidates_for_image(length: int) -> tuple:
    """Profiles whose full-MAT or app-only length matches `length`.

    Several parts share a geometry (all 512 KB variants), so this can return
    more than one. They agree on layout, which is what callers need.
    """
    return tuple(p for p in PROFILES if length in (p.mat_size, p.app_size))


def resolve_image_layout(length: int) -> tuple:
    """-> (start, end, is_full_mat, candidate_profiles) for an image length.

    Raises if the length matches no known profile, or if matching profiles
    disagree on geometry (which would make the write target ambiguous).
    """
    cands = candidates_for_image(length)
    if not cands:
        known = ", ".join(
            f"0x{p.mat_size:X}/0x{p.app_size:X} ({p.key})" for p in PROFILES
        )
        raise RuntimeError(
            f"unsupported image length 0x{length:X}; known full/app sizes: {known}"
        )
    layouts = set()
    for p in cands:
        if length == p.mat_size:
            layouts.add((0x0000, p.mat_size, True))
        else:
            layouts.add((p.app_start, p.app_end, False))
    if len(layouts) != 1:
        raise RuntimeError(
            f"image length 0x{length:X} is ambiguous across profiles: "
            + ", ".join(p.key for p in cands)
        )
    start, end, is_full = layouts.pop()
    return start, end, is_full, cands


def app_slice_bounds(length: int) -> tuple:
    """-> (start, end) of the application payload *within the given image*.

    For a full-MAT image the app is a window inside it; for an app-only image
    the whole file is the app.
    """
    start, end, is_full, cands = resolve_image_layout(length)
    p = cands[0]
    if is_full:
        return p.app_start, p.app_end
    return 0, length


def checksum_offsets_for_app(app_length: int) -> tuple:
    for p in PROFILES:
        if p.app_size == app_length:
            return p.checksum_offsets
    raise RuntimeError(
        f"no embedded-checksum definition for app length 0x{app_length:X}"
    )


if __name__ == "__main__":
    print("Honda SH-2A EPS profiles")
    for p in PROFILES:
        print("  " + p.describe())
        sums = ", ".join(f"0x{o:X}" for _k, o in p.checksum_offsets)
        print(f"           checksums @ {sums}   {p.notes}")
