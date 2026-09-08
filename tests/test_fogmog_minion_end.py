"""FOGMOG 终局判定(2026-09-02) —— primary 死亡时 minion 不阻断判胜。

背景:上游 `_check_combat_end` 的胜利条件 = alive_enemies 空(含 minion)。
FOGMOG 的召唤物 EyeWithTeeth 带 MINION+ILLUSION(死亡即满血复活),fogmog
死亡后 minion 永远在场 → 战斗永不结束 → run_env 201 回合上限强制判负。
C# 语义(CreatureCmd.cs:376 + Creature.IsSecondaryEnemy):primary 死亡时
引擎 Kill 全部 secondary → 立即判胜。datawash patch 对齐该语义。

取证:回合上限僵局的 FOGMOG 对局里 fogmog 均已 0 HP ——
纯环境假死锁。
"""

import pytest

from sts2_env.datawash.patch import install_v01110_overrides


def _mk_fogmog_combat():
    install_v01110_overrides()
    from sts2_env.cards.base import reset_instance_counter
    from sts2_env.cards.ironclad_basic import create_ironclad_starter_deck
    from sts2_env.core.combat import CombatState
    from sts2_env.core.enums import PowerId
    from sts2_env.core.rng import Rng
    from sts2_env.monsters.act1 import create_eye_with_teeth, create_fogmog

    reset_instance_counter()
    rng = Rng(42)
    combat = CombatState(
        player_hp=80, player_max_hp=80, deck=create_ironclad_starter_deck(), rng_seed=42
    )
    fogmog, fog_ai = create_fogmog(rng)
    combat.add_enemy(fogmog, fog_ai)
    eye, eye_ai = create_eye_with_teeth(rng)
    combat.add_enemy(eye, eye_ai)
    combat.start_combat()
    return combat, fogmog, eye, PowerId


def test_fogmog_death_wins_despite_living_minion():
    """fogmog(非 MINION)死亡、eye(minion)存活 → 立即判胜(修复核心)。"""
    combat, fogmog, _eye, _pid = _mk_fogmog_combat()
    fogmog.current_hp = 0
    combat._check_combat_end()
    assert combat.is_over
    assert combat.player_won


def test_minion_alive_alone_also_wins_once_primary_gone():
    """eye(minion)是唯一活敌(primary 已死/被移除)→ 判胜,不进入复活死锁。"""
    combat, fogmog, eye, _pid = _mk_fogmog_combat()
    fogmog.current_hp = 0
    eye.current_hp = 6
    combat._check_combat_end()
    assert combat.is_over and combat.player_won


def test_primary_alive_does_not_end():
    """两敌都活 → 不终局(无行为变化)。"""
    combat, fogmog, eye, _pid = _mk_fogmog_combat()
    fogmog.current_hp = 40
    eye.current_hp = 6
    combat._check_combat_end()
    assert not combat.is_over


def test_eye_dead_primary_alive_does_not_end():
    """eye 死(fogmog 活)→ 不终局 —— 修复只放行 primary 全灭。"""
    combat, fogmog, eye, _pid = _mk_fogmog_combat()
    fogmog.current_hp = 40
    eye.current_hp = 0
    combat._check_combat_end()
    assert not combat.is_over


def test_player_death_still_loses():
    """玩家死亡 → 判负(原语义不动)。"""
    combat, _fogmog, _eye, _pid = _mk_fogmog_combat()
    combat.primary_player.current_hp = 0
    combat._check_combat_end()
    assert combat.is_over
    assert not combat.player_won


def test_plain_enemies_unaffected():
    """无 minion 的普通场:单杀不终局、全灭判胜(原语义回归)。"""
    install_v01110_overrides()
    from sts2_env.cards.base import reset_instance_counter
    from sts2_env.cards.ironclad_basic import create_ironclad_starter_deck
    from sts2_env.core.combat import CombatState
    from sts2_env.core.rng import Rng
    from sts2_env.monsters.act1_weak import create_shrinker_beetle

    reset_instance_counter()
    rng = Rng(42)
    combat = CombatState(
        player_hp=80, player_max_hp=80, deck=create_ironclad_starter_deck(), rng_seed=42
    )
    for _ in range(2):
        creature, ai = create_shrinker_beetle(rng)
        combat.add_enemy(creature, ai)
    combat.start_combat()
    a, b = combat.enemies
    a.current_hp = 0
    combat._check_combat_end()
    assert not combat.is_over
    b.current_hp = 0
    combat._check_combat_end()
    assert combat.is_over and combat.player_won


def test_reviving_primary_still_blocks():
    """primary 死体处于复活中(is_reviving power)→ 阻断判胜(原语义保留)。

    注:不能用 apply_power(ILLUSION) 构造 —— ILLUSION 的
    after_power_amount_changed 会给非 MINION owner 自动补 MINION
    (C# AfterApplied 同款),挂上即变 minion。故手工挂假 power。
    """
    combat, fogmog, _eye, pid = _mk_fogmog_combat()

    class _RevivingFakePower:
        is_reviving = True

    fogmog.current_hp = 0
    fogmog.powers[pid.STRENGTH] = _RevivingFakePower()
    combat._check_combat_end()
    assert not combat.is_over


def test_eye_has_minion_and_illusion_powers():
    """power 注册链守护:create_eye_with_teeth 必须真实挂上 MINION+ILLUSION。

    回归对象是「谁 import 谁注册」陷阱:缺 sts2_env.powers 导入时
    Creature.apply_power 对未知 PowerId 静默降级,eye 变普通怪 —— 终局
    语义与复活行为全部失真。patch.install_v01110_overrides 负责显式注册。
    """
    _combat, _fogmog, eye, pid = _mk_fogmog_combat()
    assert pid.MINION in eye.powers
    assert pid.ILLUSION in eye.powers
