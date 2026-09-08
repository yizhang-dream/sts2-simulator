"""RNG 接线行为锁（点2/点4/点5）。

C# 权威:
- 点2: CombatState.cs:136 per-creature rng 公式
    ``new Rng((uint)((RunState.Rng.Seed + CurrentMapCoord?.col)
                     ?? ((long?)CurrentMapCoord?.row)
                     ?? (CurrentActIndex + CombatId.Value)))``
- 点4: CombatState.cs:127 ``monster.RunRng = RunState.Rng``（整组 run 流引用）；
    CombatState.cs:132 敌方生物 HP 变体消费 ``RunState.Rng.Niche``；
    Fabricator.cs:105 出怪选择 ``RunRng.MonsterAi.NextItem``。
- 点5: Player.cs:225 + PlayerRngSet.cs:31-34 + NGame.cs:769 玩家流种子基底
    = (uint)(hash(seed) + NetId)，单玩家 NetId=1（即 Python 的 +1 有据）；
    每条流 = 基底 + (uint)hash(snake_case(类型名))。
"""

import pytest

import sts2_env.powers  # noqa: F401  # 确保 power 注册
from sts2_env.cards.ironclad_basic import create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.creature import Creature
from sts2_env.core.enums import CombatSide
from sts2_env.core.rng import UINT_MASK, Rng, deterministic_hash_code
from sts2_env.map.map_point import MapCoord
from sts2_env.monsters.act3 import (
    FABRICATOR_FABRICATE_MOVE,
    create_fabricator,
)
from sts2_env.run.run_state import RunRngSet, RunState

_UINT32 = UINT_MASK


def _uint32(value: int) -> int:
    return value & _UINT32


def _make_combat(run_state: RunState, rng_seed: int) -> CombatState:
    """构造挂了 run 上下文的战斗（与 run_manager._enter_combat 同参链）。"""
    return CombatState(
        player_hp=80,
        player_max_hp=80,
        deck=create_ironclad_starter_deck(),
        rng_seed=rng_seed,
        player_state=run_state.player,
        character_id="Ironclad",
    )


# ---------------------------------------------------------------------------
# 点5: 玩家流种子派生（run_state.RunRngSet）
# ---------------------------------------------------------------------------


def test_player_rng_streams_seed_equals_csharp_derivation():
    """点5 逐行核对结论: Python 现状已与 C# 对齐，+1 即单玩家 NetId=1。

    C# 依据链: Player.cs:225 InitializeSeed →
    ``PlayerRng = new PlayerRngSet((uint)((ulong)hash(seed) + NetId))``；
    单玩家路径 NGame.cs:769 硬编码 ``CreateForNewRun(..., 1uL)``；
    PlayerRngSet.cs:31-34 每条流 = new Rng(Seed, SnakeCase(类型名))，
    即基底 + (uint)hash(name)。本测试把该公式（含 +1）锁死。
    """
    master_seed = 424242
    rng_set = RunRngSet(master_seed)
    base = _uint32(deterministic_hash_code(str(master_seed)))
    # run 流基底 = (uint)hash(str(seed))；流种子 = base + (uint)hash(流名)
    assert rng_set.up_front.seed == _uint32(base + _uint32(deterministic_hash_code("up_front")))
    # 玩家流基底 = hash + NetId(单玩家=1)；流种子 = base+1 + (uint)hash(流名)
    player_base = _uint32(base + 1)
    for name in ("rewards", "shops", "transformations"):
        rng = getattr(rng_set, name)
        expected = _uint32(player_base + _uint32(deterministic_hash_code(name)))
        assert rng.seed == expected, name


def test_runrngset_same_seed_fully_deterministic():
    streams = (
        "up_front",
        "shuffle",
        "unknown_map_point",
        "combat_card_generation",
        "combat_potion_generation",
        "combat_card_selection",
        "combat_energy_costs",
        "combat_targets",
        "monster_ai",
        "niche",
        "combat_orbs",
        "treasure_room",
        "rewards",
        "shops",
        "transformations",
    )
    a, b = RunRngSet(7), RunRngSet(7)
    for name in streams:
        assert getattr(a, name).seed == getattr(b, name).seed, name
        assert getattr(a, name).counter == getattr(b, name).counter, name


# ---------------------------------------------------------------------------
# 点2: 战斗级 rng 种子 = C# CombatState.cs:136 公式
# ---------------------------------------------------------------------------


def test_combat_rng_seed_uses_formula_with_map_coord():
    run_state = RunState(seed=1001, character_id="Ironclad")
    run_state.add_visited_coord(MapCoord(col=3, row=5))
    combat = _make_combat(run_state, rng_seed=999)
    base = _uint32(deterministic_hash_code("1001"))
    # C# 公式 coord 分支: (uint)((long)(uint)Seed + col)——row 分支不可达，
    # 公式不消费 combat_id
    assert combat.rng.seed == _uint32(base + 3)


def test_combat_rng_seed_falls_back_to_act_index_without_coord():
    run_state = RunState(seed=1001, character_id="Ironclad")
    # 未访问任何坐标 ⇒ C# CurrentMapCoord 为 null ⇒ 回退分支 ActIndex + CombatId
    combat = _make_combat(run_state, rng_seed=999)
    assert combat.rng.seed == _uint32(0 + 0)
    run_state.current_act_index = 2
    combat_act3 = _make_combat(run_state, rng_seed=999)
    assert combat_act3.rng.seed == _uint32(2 + 0)


def test_combat_rng_seed_passthrough_without_run_context():
    deck = create_ironclad_starter_deck()
    combat = CombatState(
        player_hp=80,
        player_max_hp=80,
        deck=list(deck),
        rng_seed=123456,
        character_id="Ironclad",
    )
    # 无 run 上下文（独立对局/测试直构）⇒ 维持传入 rng_seed
    assert combat.rng.seed == _uint32(123456)


def test_derive_creature_rng_seed_follows_formula_and_coord():
    run_state = RunState(seed=5, character_id="Ironclad")
    combat = _make_combat(run_state, rng_seed=1)
    base = _uint32(deterministic_hash_code("5"))
    # 无坐标: 回退分支 = act_index + combat_id
    assert combat.derive_creature_rng_seed(7) == _uint32(0 + 7)
    # 有坐标: Seed + col（combat_id 不进公式）
    run_state.add_visited_coord(MapCoord(col=2, row=3))
    assert combat.derive_creature_rng_seed(7) == _uint32(base + 2)


def test_combat_rng_same_run_seed_bit_identical():
    seeds = []
    for _ in range(2):
        run_state = RunState(seed=4242, character_id="Ironclad")
        run_state.add_visited_coord(MapCoord(col=4, row=1))
        combat = _make_combat(run_state, rng_seed=31337)
        seeds.append((combat.rng.seed, combat.rng.counter))
    assert seeds[0] == seeds[1]


# ---------------------------------------------------------------------------
# 点4: 出怪随机接 run 流
# ---------------------------------------------------------------------------


def _fresh_run_combat(run_seed: int):
    run_state = RunState(seed=run_seed, character_id="Ironclad")
    run_state.add_visited_coord(MapCoord(col=6, row=2))
    combat = _make_combat(run_state, rng_seed=1)
    return run_state, combat


def test_fabricator_spawn_selection_draws_monster_ai_stream():
    run_state, combat = _fresh_run_combat(77)
    fabricator, fabricator_ai = create_fabricator(Rng(6))
    combat.add_enemy(fabricator, fabricator_ai)
    before = run_state.rng.monster_ai.counter
    # C# Fabricator.cs:105: FABRICATE = defense + aggro 两次 RunRng.MonsterAi 选择
    fabricator_ai.states[FABRICATOR_FABRICATE_MOVE].perform(combat)
    assert len(combat.enemies) == 3
    assert run_state.rng.monster_ai.counter - before == 2


def test_fabricator_spawn_same_seed_bit_identical():
    results = []
    for _ in range(2):
        run_state, combat = _fresh_run_combat(77)
        fabricator, fabricator_ai = create_fabricator(Rng(6))
        combat.add_enemy(fabricator, fabricator_ai)
        fabricator_ai.states[FABRICATOR_FABRICATE_MOVE].perform(combat)
        results.append(
            [
                (enemy.monster_id, enemy.max_hp, enemy.current_hp)
                for enemy in combat.enemies
            ]
        )
    assert results[0] == results[1]


def test_surprise_replacements_draw_niche_stream_not_combat_rng():
    results = []
    for _ in range(2):
        run_state, combat = _fresh_run_combat(88)
        niche_before = run_state.rng.niche.counter
        combat_rng_counter_before = combat.rng.counter
        owner = Creature(
            max_hp=10,
            current_hp=10,
            side=CombatSide.ENEMY,
            monster_id="THIEF",
        )
        spawned = combat.spawn_surprise_replacements(owner)
        # C# CombatState.cs:132: 每只出怪消费一次 Niche（Sneaky + Fat = 2 抽）
        assert run_state.rng.niche.counter - niche_before == 2
        # 点2 语义: 个体 rng 为公式派生，不抽战斗级流
        assert combat.rng.counter == combat_rng_counter_before
        assert [c.monster_id for c in spawned] == ["SNEAKY_GREMLIN", "FAT_GREMLIN"]
        results.append([(c.monster_id, c.max_hp, c.current_hp) for c in spawned])
    assert results[0] == results[1]


def test_infested_wrigglers_draw_niche_stream_not_combat_rng():
    results = []
    for _ in range(2):
        run_state, combat = _fresh_run_combat(99)
        niche_before = run_state.rng.niche.counter
        combat_rng_counter_before = combat.rng.counter
        spawned = combat.spawn_infested_wrigglers(4)
        # C# InfestedPower.cs:28-33: 4 只 Wriggler = 4 次 Niche 消费
        assert run_state.rng.niche.counter - niche_before == 4
        assert combat.rng.counter == combat_rng_counter_before
        assert len(spawned) == 4
        results.append([(c.monster_id, c.max_hp, c.current_hp) for c in spawned])
    assert results[0] == results[1]


def test_spawn_falls_back_to_combat_rng_without_run_context():
    deck = create_ironclad_starter_deck()
    combat = CombatState(
        player_hp=80,
        player_max_hp=80,
        deck=list(deck),
        rng_seed=555,
        character_id="Ironclad",
    )
    owner = Creature(
        max_hp=10,
        current_hp=10,
        side=CombatSide.ENEMY,
        monster_id="THIEF",
    )
    combat_rng_counter_before = combat.rng.counter
    spawned = combat.spawn_surprise_replacements(owner)
    assert len(spawned) == 2
    # 无 run 上下文: 回退战斗内派生（独立对局兼容，确定性保持）
    assert combat.rng.counter > combat_rng_counter_before


@pytest.mark.parametrize("run_seed", [11, 2024])
def test_spawn_hp_rolls_from_niche_stream_are_repeatable(run_seed: int):
    """同 seed 同路径逐位一致（确定性回归锁）。"""
    runs = []
    for _ in range(2):
        run_state, combat = _fresh_run_combat(run_seed)
        owner = Creature(
            max_hp=10,
            current_hp=10,
            side=CombatSide.ENEMY,
            monster_id="THIEF",
        )
        surprise = combat.spawn_surprise_replacements(owner)
        wrigglers = combat.spawn_infested_wrigglers(4)
        runs.append(
            [(c.monster_id, c.max_hp) for c in surprise + wrigglers]
        )
    assert runs[0] == runs[1]
