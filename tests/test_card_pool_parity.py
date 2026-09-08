"""Card-pool behavior guards.

Reference-pool-order parity tests (which parsed the pinned reference card
pool sources) are maintained in the maintainer environment; this public
build keeps the behavior-level guards that do not need those sources.
"""

from __future__ import annotations

import subprocess
import sys

from sts2_env.cards.factory import eligible_registered_cards
from sts2_env.characters.all import get_character


def test_importing_characters_before_factory_does_not_cycle() -> None:
    script = (
        "from sts2_env.characters.all import get_character\n"
        "from sts2_env.cards.factory import eligible_registered_cards\n"
        "assert get_character('Ironclad').starting_hp == 80\n"
        "assert eligible_registered_cards(module_name='sts2_env.cards.colorless', generation_context=None)\n"
    )
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
