"""同归判定修复的行为锁(2026-09-06)。

C# CheckWinCondition(CombatManager.cs:648-661):pendingLoss(玩家死)先于
"敌全灭"判胜 → 玩家与全敌同帧死亡(毒/反伤同归)判负。Python 移植此前
胜利分支先判 → 同归判胜,胜率虚高。本文件锁定修复后的四象限语义。

测试用未绑定方法 + mock self 直接调真实的 _check_combat_end 函数体,
不构造完整 CombatState(构造依赖卡牌元数据/上游 cwd)。
"""

from types import SimpleNamespace

import sts2_env.cards.status  # noqa: F401  先行导入:破 cards↔combat 循环(直接 import core.combat 会撞 cards/__init__ 半初始化)
from sts2_env.core.combat import CombatState


def _make_combat(player_hp: int, enemies: list[dict]):
    """enemies 元素: {hp, blocking(bool)};blocking = 死体带
    should_stop_combat_ending power(阻断判胜,DoorRevival 型)。"""
    player = SimpleNamespace(current_hp=player_hp, is_dead=player_hp <= 0)
    enemy_list = []
    for spec in enemies:
        powers = {}
        if spec.get("blocking"):
            powers["blocking"] = SimpleNamespace(
                should_stop_combat_ending=lambda enemy, combat: True
            )
        enemy_list.append(SimpleNamespace(
            current_hp=spec["hp"],
            is_alive=spec["hp"] > 0,
            escaped=False,
            powers=powers,
        ))
    fake = SimpleNamespace(
        primary_player=player,
        enemies=enemy_list,
        alive_enemies=[e for e in enemy_list if e.is_alive],
        is_over=False,
        ended=None,
    )
    # is_over 同步置位:全套件下 patch.py 已把 _check_combat_end 换成
    # minion 终局 wrapper(读 self.is_over),fake 必须走真实 wrapper 路径。
    def _end(player_won):
        fake.ended = player_won
        fake.is_over = True
    fake._end_combat = _end
    return fake


def _check(fake):
    CombatState._check_combat_end(fake)


def test_mutual_death_is_loss():
    """同归(玩家+全敌同帧死)→ 判负(C# pendingLoss 优先)。"""
    fake = _make_combat(player_hp=0, enemies=[{"hp": 0}, {"hp": 0}])
    _check(fake)
    assert fake.ended is False


def test_mutual_death_single_enemy_is_loss():
    fake = _make_combat(player_hp=0, enemies=[{"hp": 0}])
    _check(fake)
    assert fake.ended is False


def test_player_alive_all_enemies_dead_is_win():
    fake = _make_combat(player_hp=30, enemies=[{"hp": 0}])
    _check(fake)
    assert fake.ended is True


def test_player_dead_enemies_alive_is_loss():
    fake = _make_combat(player_hp=0, enemies=[{"hp": 10}])
    _check(fake)
    assert fake.ended is False


def test_blocking_dead_enemy_prevents_end_when_player_alive():
    fake = _make_combat(player_hp=30, enemies=[{"hp": 0, "blocking": True}])
    _check(fake)
    assert fake.ended is None


def test_player_dead_with_blocking_dead_enemy_is_loss():
    """玩家死优先于阻断判胜的锁死分支:同归+blocking 死体 → 判负。"""
    fake = _make_combat(player_hp=0, enemies=[{"hp": 0, "blocking": True}])
    _check(fake)
    assert fake.ended is False
