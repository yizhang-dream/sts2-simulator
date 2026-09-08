"""RunState.relics 构造期别名冻结(2026-09-03) —— 拾取遗物全失效。

上游 RunState.__init__ 把 ``self.relics`` 绑定为 ``self.player.relics`` 当时
指向的 list 对象;首场战斗构造时 ``CombatState._build_player_state`` 把
``player_state.relics`` 重绑到 normalize 后的新 list,此后拾取遗物 append 到
新 list,``rs.relics`` 永远冻结在起始遗物。更糟的是 run_manager 两处战斗构造
传 ``relics=list(rs.relics)``(陈旧别名)→ ``_build_player_state`` 的
``if relics:`` 分支每场战斗把 ``player.relics`` 重置回 [CRACKED_CORE] ——
拾取的遗物在下场战斗开打前被抹掉,遗物效果从不生效。

修复:datawash patch 把 RunState.relics 改为活 property。本文件三道回归:
1) 活别名语义(读跟随 player.relics,重绑后仍跟随,且为同一对象);
2) 复现原始 bug 场景:拾取遗物 → 按 run_manager 同构参数构造 CombatState →
   修复前 player.relics 被重置回起始遗物,修复后保留;
3) 战斗侧视角一致:combat.relics / combat 玩家遗物对象都含拾取遗物。
"""

import pytest

from sts2_env.datawash.patch import install_v01110_overrides

ACQUIRED = "BURNING_BLOOD"  # 任一非起始遗物;registry 真实 id


def _mk_run_state():
    install_v01110_overrides()
    from sts2_env.run.run_state import RunState

    rs = RunState(character_id="Ironclad")
    rs.player.relics.append("CRACKED_CORE")
    return rs


def test_relic_alias_is_live_property():
    rs = _mk_run_state()
    # 读跟随 player,且为同一对象(修复前 init 后也同对象,但重绑后断开)
    assert rs.relics is rs.player.relics
    rs.player.relics.append(ACQUIRED)
    assert ACQUIRED in rs.relics
    # 模拟 CombatState._build_player_state 的重绑:player.relics = 新 list
    rs.player.relics = ["CRACKED_CORE", ACQUIRED]
    assert rs.relics is rs.player.relics
    assert rs.relics == ["CRACKED_CORE", ACQUIRED]


def test_combat_construction_preserves_acquired_relics():
    """run_manager._setup_combat 同构调用:relics=list(rs.relics) 不得抹掉拾取。"""
    rs = _mk_run_state()
    rs.player.relics.append(ACQUIRED)

    from sts2_env.cards.base import reset_instance_counter
    from sts2_env.cards.ironclad_basic import create_ironclad_starter_deck
    from sts2_env.core.combat import CombatState

    reset_instance_counter()
    combat = CombatState(
        player_hp=80,
        player_max_hp=80,
        deck=create_ironclad_starter_deck(),
        rng_seed=7,
        relics=list(rs.relics),
        gold=99,
        character_id="Ironclad",
        potions=[],
        max_potion_slots=3,
        player_state=rs.player,
    )
    # 修复前:传进去的是陈旧别名 ['CRACKED_CORE'],_build_player_state 把
    # player.relics 重置 → 拾取遗物丢失。修复后:活别名 → 内容保留。
    # 注:combat 侧列表元素经 _coerce_relics 可能是 RelicId 枚举,按名字比。
    assert ACQUIRED in rs.player.relics
    assert rs.relics is rs.player.relics
    combat_names = {
        str(getattr(r, "name", r)).rsplit(".", 1)[-1] for r in combat.relics
    }
    assert combat_names == {"CRACKED_CORE", ACQUIRED}


def test_combat_side_relic_objects_contain_acquired():
    """战斗内权威视角(combat player 的遗物对象)也必须看到拾取遗物。"""
    rs = _mk_run_state()
    rs.player.relics.append(ACQUIRED)

    from sts2_env.cards.base import reset_instance_counter
    from sts2_env.cards.ironclad_basic import create_ironclad_starter_deck
    from sts2_env.core.combat import CombatState

    reset_instance_counter()
    combat = CombatState(
        player_hp=80,
        player_max_hp=80,
        deck=create_ironclad_starter_deck(),
        rng_seed=7,
        relics=list(rs.relics),
        player_state=rs.player,
    )
    combat.start_combat()
    names = {str(getattr(r, "relic_id", r)).rsplit(".", 1)[-1] for r in combat.relics}
    assert "CRACKED_CORE" in names and ACQUIRED in names
