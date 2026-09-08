"""Hook 派发顺序修复锁测试:对齐 C# IterateHookListeners。

C# 权威:CombatState.cs:264-315(交错序:友方先敌方后,每生物
[powers→玩家侧 relics])+ Hook.cs:1902-1946(ModifyDamageInternal =
同一交错序列两遍扫描:第一遍全体 Additive(带 num),第二遍全体
Multiplicative(带 num))。

关键事实:Python
hook 签名无 num ⇒ 现有 hook 全为状态条件常数,顺序数学不可观察;本
测试锁的是**遍历结构**(未来移植 num 依赖 hook 的强制形态)。
"""

from types import SimpleNamespace

import sts2_env.cards.status  # noqa: F401  先行导入:破 cards↔core 循环
from sts2_env.core import hooks
from sts2_env.core.hooks import _iter_hook_listeners, modify_damage


def _mk_combat(player_powers, player_relics, ally_powers=(), enemy_powers=()):
    player = SimpleNamespace(powers={i: p for i, p in enumerate(player_powers)})
    ally = SimpleNamespace(powers={i: p for i, p in enumerate(ally_powers)})
    enemy = SimpleNamespace(powers={i: p for i, p in enumerate(enemy_powers)})
    pstate = SimpleNamespace(creature=player, relics=list(player_relics))
    combat = SimpleNamespace(
        all_creatures=[player, ally, enemy],
        combat_player_states=[pstate],
        player=player,
    )
    combat.relics = list(player_relics)
    return combat, player, ally, enemy


def test_interleaved_order():
    """C# 交错序:玩家 powers→玩家 relics→友方 powers→敌方 powers。"""
    P1, P2, A1, E1, E2, R1, R2 = "P1", "P2", "A1", "E1", "E2", "R1", "R2"
    combat, player, ally, enemy = _mk_combat([P1, P2], [R1, R2], [A1], [E1, E2])
    seq = [(o, k, v) for o, k, v in _iter_hook_listeners(combat)]
    assert [(k, v) for _, k, v in seq] == [
        (True, P1), (True, P2), (False, R1), (False, R2),
        (True, A1), (True, E1), (True, E2),
    ]
    owners = [o for o, _, _ in seq]
    assert owners == [player, player, player, player, ally, enemy, enemy]


def test_disabled_relic_skipped():
    """C# IsMelted 跳过 = Python enabled=False 跳过。"""
    R_off = SimpleNamespace(enabled=False)
    combat, *_ = _mk_combat(["P1"], [R_off])
    seq = [v for _, _, v in _iter_hook_listeners(combat)]
    assert R_off not in seq and "P1" in seq


def test_modify_damage_uses_interleaved_two_pass():
    """modify_damage 消费序 = 交错序两遍(加法遍,乘法遍)。

    记录每阶段实际消费的监听者序列,断言与 _iter_hook_listeners 一致。
    """
    calls = []
    _cap = float("inf")
    P1 = SimpleNamespace(modify_damage_additive=lambda *a: calls.append(("P1", "add")) or 0,
                         modify_damage_multiplicative=lambda *a: calls.append(("P1", "mult")) or 1.0,
                         modify_damage_cap=lambda *a: _cap)
    R1 = SimpleNamespace(modify_damage_additive=lambda *a: calls.append(("R1", "add")) or 0,
                         modify_damage_multiplicative=lambda *a: calls.append(("R1", "mult")) or 1.0,
                         modify_damage_cap=lambda *a: _cap)
    E1 = SimpleNamespace(modify_damage_additive=lambda *a: calls.append(("E1", "add")) or 0,
                         modify_damage_multiplicative=lambda *a: calls.append(("E1", "mult")) or 1.0,
                         modify_damage_cap=lambda *a: _cap)
    combat, *_ = _mk_combat([P1], [R1], [], [E1])
    dmg = modify_damage(10, None, combat.player, SimpleNamespace(), combat)
    assert dmg == 10
    assert calls == [("P1", "add"), ("R1", "add"), ("E1", "add"),
                     ("P1", "mult"), ("R1", "mult"), ("E1", "mult")]


def test_modify_damage_value_unchanged_by_order():
    """数值等价:交错序与旧两段序结果一致(hook 全为常数时可交换)。"""
    _cap = float("inf")
    def mk(mult_factor):
        P = SimpleNamespace(
            modify_damage_additive=lambda *a: 3,
            modify_damage_multiplicative=lambda *a: mult_factor,
            modify_damage_cap=lambda *a: _cap)
        R = SimpleNamespace(
            modify_damage_additive=lambda *a: 5,
            modify_damage_multiplicative=lambda *a: 2.0,
            modify_damage_cap=lambda *a: _cap)
        combat, *_ = _mk_combat([P], [R])
        return combat

    dmg = modify_damage(10, None, None, SimpleNamespace(), mk(1.5))
    assert dmg == int((10 + 3 + 5) * 1.5 * 2.0)  # 54
