"""Step 2 blended mix: 80% read / 20% write across the five staff-api scenarios.

Weights (Locust user spawn mix):
  register_read              40  (read)
  cr_read_and_approve        20  (read)
  intake_read_and_approve    20  (read)
  cr_create                  10  (write)
  intake_create              10  (write)
"""

from __future__ import annotations

import sys
from pathlib import Path

from shared.slo_shape import SLOStepRampShape

_STAFF_API = Path(__file__).resolve().parent.parent
for _scenario in (
    "register_read",
    "cr_create",
    "cr_read_and_approve",
    "intake_create",
    "intake_read_and_approve",
):
    _dir = str(_STAFF_API / _scenario)
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

from cr_create_locustfile import CrCreateUser
from cr_read_and_approve_locustfile import CrReadAndApproveUser
from intake_create_locustfile import IntakeCreateUser
from intake_read_and_approve_locustfile import IntakeReadAndApproveUser
from register_read_locustfile import RegisterUser


class BlendedRampShape(SLOStepRampShape):
    """Same SLO/CPU ramp as isolated, for the 80:20 read:write mix."""


RegisterUser.weight = 40
CrReadAndApproveUser.weight = 20
IntakeReadAndApproveUser.weight = 20
CrCreateUser.weight = 10
IntakeCreateUser.weight = 10
