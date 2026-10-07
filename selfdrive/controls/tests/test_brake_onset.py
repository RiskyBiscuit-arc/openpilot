from types import SimpleNamespace

import pytest

from openpilot.selfdrive.controls.lib import longitudinal_planner as lp


def _lead(d, v_rel, a=0.0, status=True):
  return SimpleNamespace(status=status, dRel=d, vRel=v_rel, aLeadK=a)


def test_limited_target_slows_only_a_falling_target():
  dt = 0.05
  assert lp.brake_onset_limited_target(-0.2, -1.5, dt, 1.5) == pytest.approx(-0.2 - 1.5 * dt)
  assert lp.brake_onset_limited_target(-1.0, -0.5, dt, 1.5) == pytest.approx(-0.5)  # release untouched
  assert lp.brake_onset_limited_target(-0.2, -1.5, dt, None) == pytest.approx(-1.5)
  assert lp.brake_onset_limited_target(1.0, 0.03, dt, 1.5) == pytest.approx(0.03)   # throttle cut untouched
  assert lp.brake_onset_limited_target(0.8, -1.0, dt, 1.5) == pytest.approx(-1.5 * dt)  # ramps from 0, not from +0.8


def test_ramp_reaches_the_target_within_abs_a_over_j():
  a, dt, j = 0.0, 0.05, 1.5
  for _ in range(int(1.5 / (j * dt)) + 1):
    a = lp.brake_onset_limited_target(a, -1.5, dt, j)
  assert a == pytest.approx(-1.5)


def test_smooth_brake_onset_is_removed_for_stock_brake_feel():
  # D-086: the owner asked for one toggle, not two, and then for the Smooth Brake Onset code to go too.
  from pathlib import Path
  root = Path(__file__).resolve().parents[3]
  for f in ("starpilot/common/assets/device_settings_layout.json", "selfdrive/ui/layouts/settings/starpilot/longitudinal.py",
            "common/params_keys.h", "starpilot/common/starpilot_variables.py"):
    assert "BrakeOnsetLimit" not in (root / f).read_text(), f
  src = (root / "selfdrive/controls/lib/longitudinal_planner.py").read_text()
  assert '"brake_onset_limit"' not in src and not hasattr(lp, "BRAKE_ONSET_LIMIT") and not hasattr(lp, "stock_onset_jerk")


# D-080: newborn radar lead aLeadK bound, part of the StockBrakeFeel toggle.
def _rlead(tid, d, a, v_rel=-2.0, radar=True):
  return SimpleNamespace(status=True, radar=radar, radarTrackId=tid, dRel=d, vRel=v_rel, aLeadK=a)


def _sm(lead_one, lead_two=None, a_ego=0.0):
  lead_two = lead_two or SimpleNamespace(status=False, radar=False)
  return {'radarState': SimpleNamespace(leadOne=lead_one, leadTwo=lead_two), 'carState': SimpleNamespace(aEgo=a_ego)}


def _run(hold, frames):
  """frames: list of (lead_one, lead_two, a_ego); returns the planner-side leadOne aLeadK per frame."""
  out = []
  for one, two, a_ego in frames:
    out.append(float(lp.bound_newborn_leads(_sm(one, two, a_ego), hold)['radarState'].leadOne.aLeadK))
  return out


def test_newborn_lead_hard_brake_is_bounded_then_released_after_two_seconds():
  hold = lp.NewbornLeadHold()
  # constant closing speed: range history shows no lead decel
  a = _run(hold, [(_rlead(7, 60.0 - 0.1 * i, -3.0), None, 0.0) for i in range(lp.NEWBORN_LEAD_FRAMES + 5)])
  assert all(x == pytest.approx(-lp.NEWBORN_LEAD_MIN_BRAKE) for x in a[:lp.NEWBORN_LEAD_FRAMES])
  assert all(x == -3.0 for x in a[lp.NEWBORN_LEAD_FRAMES:])


def test_bound_only_touches_aleadk_and_never_drops_the_lead():
  hold = lp.NewbornLeadHold()
  lead = _rlead(3, 40.0, -5.0, v_rel=-4.0)
  out = lp.bound_newborn_leads(_sm(lead), hold)['radarState'].leadOne
  assert out.aLeadK == pytest.approx(-1.0)
  assert (out.dRel, out.vRel, out.status, out.radarTrackId) == (40.0, -4.0, True, 3)


@pytest.mark.parametrize("lead", [_rlead(1, 50.0, -0.5), _rlead(1, 50.0, -3.0, radar=False),
                                  SimpleNamespace(status=False, radar=True, radarTrackId=1, dRel=50.0, aLeadK=-3.0)])
def test_mild_vision_only_or_inactive_leads_pass_through(lead):
  hold = lp.NewbornLeadHold()
  sm = _sm(lead)
  assert lp.bound_newborn_leads(sm, hold) is sm


def test_range_history_that_shows_lead_braking_lowers_the_floor():
  hold = lp.NewbornLeadHold()
  # ego steady, lead decelerating at -3 m/s^2 from a 2 m/s closing: d = 60 - 2t - 1.5 t^2
  frames = []
  for i in range(30):
    t = i * lp.DT_MDL
    frames.append((_rlead(9, 60.0 - 2.0 * t - 1.5 * t * t, -3.0), None, 0.0))
  a = _run(hold, frames)
  assert a[lp.NEWBORN_LEAD_FIT_FRAMES - 2] == pytest.approx(-1.0)
  assert a[-1] == pytest.approx(-3.0, abs=0.05)


def test_dropout_or_range_jump_makes_a_track_newborn_again():
  hold = lp.NewbornLeadHold()
  _run(hold, [(_rlead(5, 50.0, 0.0, v_rel=0.0), None, 0.0) for _ in range(lp.NEWBORN_LEAD_FRAMES + 2)])
  assert _run(hold, [(_rlead(5, 50.0, -4.0, v_rel=0.0), None, 0.0)]) == [-4.0]  # mature: untouched
  assert _run(hold, [(_rlead(5, 50.0 - lp.NEWBORN_LEAD_JUMP_M - 1.0, -4.0, v_rel=0.0), None, 0.0)]) == [-1.0]
  hold2 = lp.NewbornLeadHold()
  _run(hold2, [(_rlead(6, 50.0, 0.0, v_rel=0.0), None, 0.0) for _ in range(lp.NEWBORN_LEAD_FRAMES + 2)])
  absent = SimpleNamespace(status=False, radar=False, aLeadK=0.0)
  _run(hold2, [(absent, None, 0.0) for _ in range(lp.NEWBORN_LEAD_GAP_FRAMES + 1)])
  assert _run(hold2, [(_rlead(6, 50.0, -4.0, v_rel=0.0), None, 0.0)]) == [-1.0]


def test_same_track_as_lead_one_and_two_is_recorded_once_per_frame():
  hold = lp.NewbornLeadHold()
  lead = _rlead(4, 30.0, -3.0)
  lp.bound_newborn_leads(_sm(lead, lead), hold)
  assert len(hold.hist[4]) == 1


def test_bound_is_applied_only_when_stock_brake_feel_is_on():
  import inspect
  src = inspect.getsource(lp.LongitudinalPlanner._update)
  gate = 'if bool(getattr(starpilot_toggles, "stock_brake_feel", False)):\n'
  assert gate + '      sm = bound_newborn_leads(sm, self.newborn_lead_hold)' in src


# D-086: StockBrakeFeel toggle, stock Honda ACC depth and rate by TTC.
def test_stock_feel_toggle_is_wired_and_off_by_default():
  import json
  from pathlib import Path
  root = Path(__file__).resolve().parents[3]
  layout = json.loads((root / "starpilot/common/assets/device_settings_layout.json").read_text())
  found = []

  def walk(node):
    if isinstance(node, dict):
      if node.get("key") == "StockBrakeFeel":
        found.append(node)
      for v in node.values():
        walk(v)
    elif isinstance(node, list):
      for v in node:
        walk(v)
  walk(layout)
  assert len(found) == 1
  assert found[0]["parent_key"] == "AdvancedLongitudinalTune" and found[0]["ui_type"] == "toggle"
  assert 'SettingRow("StockBrakeFeel", "toggle"' in (root / "selfdrive/ui/layouts/settings/starpilot/longitudinal.py").read_text()
  assert '{"StockBrakeFeel", {PERSISTENT, BOOL, "0", "0", 3}}' in (root / "common/params_keys.h").read_text()
  assert 'toggle.stock_brake_feel = False' in (root / "starpilot/common/starpilot_variables.py").read_text()
  src = Path(lp.__file__).read_text()
  assert 'getattr(starpilot_toggles, "stock_brake_feel", False)' in src


def test_stock_feel_depth_follows_stock_by_ttc():
  # 100 m closing 8 m/s (TTC 12.5): planner -3.0 held at stock's ~-0.93; 30 m closing 10 m/s (TTC 3): ~-2.37
  assert lp.stock_feel_target((_lead(100.0, -8.0),), -3.0, -3.0, 0.05) == pytest.approx(
    float(lp.np.interp(12.5, lp.STOCK_FEEL_DEPTH_BP, lp.STOCK_FEEL_DEPTH_V)))
  assert lp.stock_feel_target((_lead(30.0, -10.0),), -3.0, -3.0, 0.05) == pytest.approx(
    float(lp.np.interp(3.0, lp.STOCK_FEEL_DEPTH_BP, lp.STOCK_FEEL_DEPTH_V)))
  assert lp.stock_feel_target((_lead(100.0, -8.0),), -0.58, -0.6, 0.05) == pytest.approx(-0.6)  # shallower, slow: untouched


def test_stock_feel_ignores_the_gap_and_lead_braking_gates_like_stock():
  # 12 m at 20 m/s (inside 1.5 s of gap) closing 4 m/s, lead braking -3: TTC 3 s, still stock's depth
  assert lp.stock_feel_target((_lead(12.0, -4.0, a=-3.0),), -3.5, -3.5, 0.05) > -2.5


def test_stock_feel_deepens_at_stock_rate():
  far = (_lead(150.0, -10.0),)   # TTC 15 s: depth ~-0.80, rate ~0.6 m/s^3
  assert lp.stock_feel_target(far, -0.2, -0.8, 0.05) == pytest.approx(-0.2 - 0.6 * 0.05)
  mid = (_lead(60.0, -10.0),)    # TTC 6 s: rate 1.0
  assert lp.stock_feel_target(mid, -0.5, -2.0, 0.05) == pytest.approx(-0.55)
  assert lp.stock_feel_target(mid, -1.5, -0.5, 0.05) == pytest.approx(-0.5)  # release untouched


@pytest.mark.parametrize("leads", [
  (_lead(30.0, -16.0),),          # TTC 1.9 s: under the floor, stock itself is at -3.8..-4
  (_lead(30.0, 1.0),),            # opening
  (_lead(30.0, -0.3),),           # closing under 0.5 m/s
  (_lead(30.0, -10.0, status=False),),
])
def test_stock_feel_keeps_planner_depth_but_limits_the_step(leads):
  # Outside the fitted law the depth is the planner's; only the per-frame deepening is bounded (STATUS 220 replay steps).
  assert lp.stock_feel_target(leads, -3.5, -3.5, 0.05) == -3.5
  assert lp.stock_feel_target(leads, 0.0, -3.5, 0.05) == pytest.approx(-lp.STOCK_FEEL_JERK_OUTSIDE * 0.05)
  assert lp.stock_feel_target(leads, -2.0, -1.0, 0.05) == -1.0


def test_stock_feel_depth_table_is_monotone():
  assert all(a < b for a, b in zip(lp.STOCK_FEEL_DEPTH_BP[:-1], lp.STOCK_FEEL_DEPTH_BP[1:], strict=True))
  assert all(a <= b for a, b in zip(lp.STOCK_FEEL_DEPTH_V[:-1], lp.STOCK_FEEL_DEPTH_V[1:], strict=True))
  assert lp.STOCK_FEEL_DEPTH_V[0] <= -3.5 and len(lp.STOCK_FEEL_DEPTH_BP) == len(lp.STOCK_FEEL_DEPTH_V)


# Coast to the lead (owner, 2026-10-07), part of the StockBrakeFeel toggle.
def _clead(d, v_rel, v_lead, status=True):
  return SimpleNamespace(status=status, dRel=d, vRel=v_rel, vLead=v_lead, aLeadK=0.0)


def test_lead_coast_starts_when_closing_inside_two_follow_distances():
  # 2ed 21:34-like: 10 m/s behind a 9 m/s lead at 15 m, follow distance 1.45 * 9 + 6 = 19 m
  assert lp.lead_coast_wanted((_clead(15.0, -1.0, 9.0),), 10.0, 1.45, False)
  assert lp.lead_coast_wanted((_clead(37.0, -1.0, 9.0),), 10.0, 1.45, False)      # 1.95x
  assert not lp.lead_coast_wanted((_clead(39.0, -1.0, 9.0),), 10.0, 1.45, False)  # 2.05x
  assert not lp.lead_coast_wanted((_clead(15.0, 0.5, 10.5),), 10.0, 1.45, False)  # lead pulling away
  assert not lp.lead_coast_wanted((_clead(15.0, -0.3, 9.7),), 10.0, 1.45, False)  # barely closing
  assert not lp.lead_coast_wanted((_clead(5.0, -1.0, 0.5),), 1.5, 1.45, False)    # creep: planner's
  assert not lp.lead_coast_wanted((_clead(15.0, -1.0, 9.0, status=False),), 10.0, 1.45, False)


def test_lead_coast_holds_speed_first_and_coasts_at_stocks_let_off_point():
  H, C = lp.LEAD_COAST_HOLD, lp.LEAD_COAST_COAST
  # follow distance 19 m (9 m/s lead); stock lets off the gas at closing p50 1.28 m/s inside 1.61x (0.07 m/s^2 needed)
  assert lp.lead_coast_wanted((_clead(35.0, -1.0, 9.0),), 10.0, 1.45, 0) == H      # 1 m/s at 1.84x: stop speeding up
  assert lp.lead_coast_wanted((_clead(30.0, -1.3, 9.0),), 10.0, 1.45, 0) == C      # 1.3 m/s at 1.58x: coast
  assert lp.lead_coast_wanted((_clead(32.0, -1.3, 9.0),), 10.0, 1.45, 0) == H      # 1.68x: not yet
  assert lp.lead_coast_wanted((_clead(18.0, -0.6, 9.0),), 10.0, 1.45, 0) == C      # inside the follow distance: coast
  assert lp.lead_coast_wanted((_clead(28.0, -0.6, 9.0),), 10.0, 1.45, 0) == C      # slow closing at 1.47x: coast
  assert lp.lead_coast_wanted((_clead(30.0, -0.6, 9.0),), 10.0, 1.45, 0) == H      # 1.58x: not yet
  # once coasting it stays a coast until the closing ends, as stock does
  assert lp.lead_coast_wanted((_clead(20.0, -0.3, 9.7),), 10.0, 1.45, C) == C
  assert lp.lead_coast_wanted((_clead(20.0, -0.3, 9.7),), 10.0, 1.45, H) == H
  assert lp.lead_coast_wanted((_clead(20.0, -0.05, 9.95),), 10.0, 1.45, C) == lp.LEAD_COAST_OFF


def test_lead_coast_hold_ceiling_is_zero_not_the_coast():
  dt = 0.05
  c = None
  prev = 0.6
  for _ in range(40):
    c = lp.lead_coast_ceiling(c, prev, lp.LEAD_COAST_HOLD, -0.3, dt)
    prev = c
  assert c == pytest.approx(0.0)
  for _ in range(40):  # hold -> coast: falls on from 0 at the fade rate
    nxt = lp.lead_coast_ceiling(c, c, lp.LEAD_COAST_COAST, -0.3, dt)
    assert c - nxt <= lp.LEAD_COAST_FALL_JERK * dt + 1e-9
    c = nxt
  assert c == pytest.approx(-0.3)


def test_lead_coast_holds_until_speeds_match():
  assert lp.lead_coast_wanted((_clead(15.0, -0.3, 9.7),), 10.0, 1.45, True)
  assert not lp.lead_coast_wanted((_clead(15.0, -0.05, 9.95),), 10.0, 1.45, True)
  assert lp.lead_coast_wanted((_clead(41.0, -1.0, 9.0),), 10.0, 1.45, True)       # 2.16x, inside the exit ratio


def test_lead_coast_ceiling_fades_the_gas_and_gives_it_back():
  dt = 0.05
  c = lp.lead_coast_ceiling(None, 1.3, lp.LEAD_COAST_COAST, -0.3, dt)
  assert c == pytest.approx(1.3 - lp.LEAD_COAST_FALL_JERK * dt)
  for _ in range(60):
    c = lp.lead_coast_ceiling(c, c, lp.LEAD_COAST_COAST, -0.3, dt)
  assert c == pytest.approx(-0.3)
  assert lp.lead_coast_ceiling(None, 0.5, lp.LEAD_COAST_COAST, -2.0, 2.0) == pytest.approx(lp.LEAD_COAST_MIN)  # steep uphill: no brake
  assert lp.lead_coast_ceiling(None, 0.5, lp.LEAD_COAST_COAST, lp.ACCEL_MAX, 2.0) == pytest.approx(0.0)       # no pitch: hold speed
  c = lp.lead_coast_ceiling(-0.3, -1.0, lp.LEAD_COAST_OFF, -0.3, dt)  # braking below the coast: gas returns from the coast level
  assert c == pytest.approx(-0.3 + lp.LEAD_COAST_RISE_JERK * dt)
  for _ in range(200):
    c = lp.lead_coast_ceiling(c, c, lp.LEAD_COAST_OFF, -0.3, dt)
  assert c is None


def test_lead_coast_gas_returns_smoothly_from_where_the_output_is():
  # The planner held the output under the ceiling (e.g. a brief brake back up to -0.1): the gas comes back from there.
  dt = 0.05
  assert lp.lead_coast_ceiling(0.8, -0.1, lp.LEAD_COAST_OFF, -0.3, dt) == pytest.approx(-0.1 + lp.LEAD_COAST_RISE_JERK * dt)
  # Each step of the returning gas is at most the rise rate, and the fade at most the fall rate.
  c, prev = -0.3, -0.3
  for _ in range(60):
    c = lp.lead_coast_ceiling(c, prev, lp.LEAD_COAST_OFF, -0.3, dt)
    if c is None:
      break
    assert c - prev <= lp.LEAD_COAST_RISE_JERK * dt + 1e-9
    prev = c
  c, prev = None, 1.2
  for _ in range(40):
    c = lp.lead_coast_ceiling(c, prev, lp.LEAD_COAST_COAST, -0.3, dt)
    assert prev - c <= lp.LEAD_COAST_FALL_JERK * dt + 1e-9
    prev = c


def test_lead_coast_is_part_of_stock_brake_feel_and_only_lowers_the_target():
  from pathlib import Path
  src = Path(lp.__file__).read_text()
  gate = src.index('if bool(getattr(starpilot_toggles, "stock_brake_feel", False)) and not reset_state')
  use = src.index('output_a_target = min(output_a_target, self.lead_coast_ceiling)')
  law = src.index('output_a_target = stock_feel_target((self.lead_one, self.lead_two)', gate)
  assert gate < use < law


def test_lead_coast_to_brake_builds_at_stock_rate_unless_close():
  from pathlib import Path
  src = Path(lp.__file__).read_text()
  assert ("if brake_onset_ttc(leads, STOCK_FEEL_MIN_CLOSING) == float('inf') and brake_onset_ttc(leads) > STOCK_FEEL_TTC_FLOOR_S:\n"
          "          output_a_target = brake_onset_limited_target(prev_output_a_target, output_a_target, self.dt, LEAD_COAST_BRAKE_JERK)") in src
  # coasting at -0.3, barely closing (0.3 m/s at 15 m): a -1.5 planner brake builds at 1 m/s^3 from the coast level
  assert lp.brake_onset_limited_target(-0.3, -1.5, 0.05, lp.LEAD_COAST_BRAKE_JERK) == pytest.approx(-0.35)
  assert lp.brake_onset_ttc((_lead(15.0, -0.3),)) > lp.STOCK_FEEL_TTC_FLOOR_S
  assert not lp.brake_onset_ttc((_lead(3.0, -2.0),)) > lp.STOCK_FEEL_TTC_FLOOR_S  # 1.5 s: planner depth, no limit here
  # closing faster than 0.5 m/s: the stock law's own TTC rate applies instead (2 m/s^3 at TTC 2.5 s), not 1 m/s^3
  assert lp.brake_onset_ttc((_lead(5.0, -2.0),), lp.STOCK_FEEL_MIN_CLOSING) != float('inf')
