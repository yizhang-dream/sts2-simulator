"""战斗奖励拾取遗物崩溃修复回归(2026-09-05)。

链路:run_state.obtain_relic_with_setup → after_obtained(owner=PlayerState) →
PlayerState 仍挂 combat_state 引用(战斗刚结束) → 钩子走战斗内分支 →
combat_player_state_for(PlayerState) 对 dict[Creature,...] 取键崩
(unhashable)。修复 = 该方法把带 combat_state 的持久 PlayerState 映射回
root player(单玩家语义)。
"""

import pytest

from sts2_env.datawash.patch import install_v01110_overrides


def test_after_obtained_with_persistent_player_state():
    install_v01110_overrides()
    from sts2_env.core.combat import CombatState
    from sts2_env.cards.defect import create_defect_starter_deck
    from sts2_env.relics.registry import create_relic_by_name

    combat = CombatState(
        player_hp=75, player_max_hp=75, deck=create_defect_starter_deck(),
        rng_seed=1, character_id="Defect")
    combat.start_combat()
    # 复现触发条件:持久 PlayerState 挂着本战斗的引用(战斗奖励拾取时如此)
    player_state = combat.current_player_state.player_state \
        if hasattr(combat.current_player_state, "player_state") else None
    if player_state is None:
        pytest.skip("无法取持久 PlayerState,结构变更需重审")
    player_state.combat_state = combat
    relic = create_relic_by_name("ALCHEMICAL_COFFER")  # after_obtained 走战斗分支
    # 修复前:TypeError: unhashable type: 'PlayerState'
    relic.after_obtained(player_state)
