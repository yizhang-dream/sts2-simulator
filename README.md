# sts2-simulator

A headless Python simulator for **Slay the Spire 2** game rules, plus a
live-game TCP bridge to a real (installed) copy of the game.

- **Full rule chain** — combat, map generation, events, shop, relics, potions,
  card rewards, and the complete Act 1–4 run loop are reimplemented in Python.
- **Gymnasium interface** — `STS2RunEnv` exposes a full run as a standard
  `gymnasium.Env` with a discrete action space and per-step action masks.
- **Live-game bridge** — a C# mod (Harmony-based) drives the actual game over
  TCP, and a parity replay harness cross-checks simulator behavior against
  real game states.

## Data versioning

The simulator's rule structure and numbers come from one extracted-data
snapshot of a 2026-05 game build:

1. **Structure** — class structure, hooks, ordering rules, and RNG semantics
   were ported from the reference game sources of that build.
2. **Numbers and static metadata** — per-card cost/type/rarity/keywords,
   upgrade deltas, and dynamic variable values are shipped as an extracted
   snapshot in `sts2_env/cards/data/reference_static_metadata.json`, loaded
   at runtime by `sts2_env/cards/reference_static_metadata.py`.

The extraction/regeneration pipeline, the pinned reference sources, and the
later v0.111.0 numeric alignment layer (maintained as
`sts2_env/datawash/data/v01110_card_overrides.json` in the maintainer
environment) are **not** part of this public repository.

## Installation

Requires Python >= 3.11.

```bash
pip install -e ".[dev]"
```

## Quick start

Run a full game with a random legal-action policy:

```python
import numpy as np

from sts2_env.datawash.patch import install_engine_fixes
from sts2_env.gym_env.run_env import STS2RunEnv

# One-time setup: install engine-level correctness fixes (idempotent).
install_engine_fixes()

env = STS2RunEnv(character_id="Ironclad")
obs, info = env.reset(seed=42)

terminated = truncated = False
while not (terminated or truncated):
    mask = info["action_mask"]                     # legal actions this step
    action = int(np.random.choice(np.flatnonzero(mask)))
    obs, reward, terminated, truncated, info = env.step(action)

print("Run over. reward =", reward, "| floor =", info["floor"], "| hp =", info["hp"])
print("Won:", env._mgr.player_won)
```

`info["action_mask"]` is a 0/1 vector over the discrete action space and is
the supported way to enumerate legal actions in any phase (combat, map, card
rewards, shop, events, ...). For an interactive CLI against the simulator,
see `scripts/play_run_interactive.py`.

## Tests and parity

```bash
pytest
```

The public test suite locks simulator behavior: RNG stream wiring, combat
end conditions, hook dispatch order, event and potion flows, relic effects,
and exhaustive per-card unit coverage for every `CardId`. The maintainer
environment additionally runs source-level audits that cross-check the
simulator and the extracted snapshots against the pinned reference sources;
those audits and the reference sources themselves are not part of this
public repository.

## Live-game bridge

- `bridge_mod/` — C# mod that injects into the real game and exposes it over
  TCP. Build instructions: `docs/MOD_BUILD_GUIDE.md`.
- Wire protocol between the mod and Python: `docs/PROTOCOL.md`.
- `sts2_env/parity/` — parity replay harness: records states from a real game
  and replays/compares them against simulator output
  (`docs/BRIDGE_REPLAY_HARNESS.md`).
- `sts2_env/bridge/` — Python-side TCP client and state adapter.

## Repository layout

| Path | Contents |
| --- | --- |
| `sts2_env/` | Simulator package: core rules, cards, monsters, relics, potions, powers, events, map, run loop |
| `sts2_env/gym_env/` | Gymnasium environment (`STS2RunEnv`), observation/action encoding |
| `sts2_env/cards/data/` | Extracted static card metadata snapshot (JSON) |
| `sts2_env/bridge/` | TCP client/protocol/state adapter for the live game |
| `sts2_env/parity/` | Real-game state recording and replay comparison |
| `sts2_env/datawash/` | Engine-level correctness fixes (numeric override table lives in the maintainer environment) |
| `sts2_env/cli/` | Interactive command-line player |
| `sts2_env/web/` | Browser-based play UI |
| `bridge_mod/` | C# Harmony mod injected into the real game |
| `tests/` | Pytest suite incl. parity/semantic regression tests |
| `scripts/` | Interactive play and benchmark tools |
| `docs/` | Architecture, references, protocol, build and troubleshooting guides |

## Legal notice

This repository is a research-minded reimplementation of Slay the Spire 2's
game rules, made available in source form for collaborative research. No
permission to redistribute game content is granted, and this repository
contains no decompiled source text. Slay the Spire 2 is a trademark of Mega
Crit; all rights in the game belong to Mega Crit.
