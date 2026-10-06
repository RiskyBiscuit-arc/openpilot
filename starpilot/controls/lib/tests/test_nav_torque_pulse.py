from types import SimpleNamespace
from openpilot.starpilot.controls.lib.nav_torque_pulse import NavTorquePulse


def make_cs(steering_pressed=False):
  return SimpleNamespace(steeringPressed=steering_pressed)


def test_nav_torque_pulse_inactive():
  pulse = NavTorquePulse(steer_max=1.0)
  out = pulse.nudge_output_torque(False, make_cs(), 0.2)
  assert out == 0.2


def test_nav_torque_pulse_triggers_on_turn_approach():
  pulse = NavTorquePulse(steer_max=1.0)
  pulse.params_memory.put("NavInstructionState", {
    "valid": True,
    "maneuverModifier": "left",
    "maneuverDistance": 150.0,
    "currentStepIndex": "1",
  })

  # Active and within 200m -> nudges left (negative torque)
  out = pulse.nudge_output_torque(True, make_cs(), 0.0)
  assert out < 0.0

  # When driver presses steering wheel, torque pulse immediately cuts out
  out_pressed = pulse.nudge_output_torque(True, make_cs(steering_pressed=True), 0.0)
  assert out_pressed == 0.0
