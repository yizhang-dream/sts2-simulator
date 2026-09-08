"""Engine-level correctness fixes for the simulator, applied without touching it.

``install_engine_fixes()`` (alias of ``install_v01110_overrides()``) installs a
set of engine-level correctness fixes: potion-kill combat transition, end
condition semantics, RunState.relics alias freezing, and death/stuck-choice
deadlock guards. It is idempotent.

The numeric v0.111.0 card override table (``data/v01110_card_overrides.json``)
is maintained in the maintainer environment and is **not** part of this public
repository. When that table is absent, this module degrades gracefully: the
engine fixes are still installed and card numbers pass through unchanged from
the extracted-data snapshot used by ``sts2_env.cards``.

Usage (before creating any cards / envs):

    from sts2_env.datawash.patch import install_engine_fixes
    install_engine_fixes()
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

OVERRIDE_PATH = (
    Path(__file__).resolve().parent / "data" / "v01110_card_overrides.json"
)


@lru_cache(maxsize=1)
def _load_overrides() -> dict:
    # Public build ships without the numeric override table: with the table
    # absent, card numbers pass through from the extracted-data snapshot and
    # only the engine fixes below are active.
    if not OVERRIDE_PATH.exists():
        return {}
    return json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))["overrides"]


def _coerce(value, target):
    """Best-effort coerce of a JSON scalar into whatever the attribute already is."""
    try:
        return type(target)(value)
    except (TypeError, ValueError):
        return value


def _apply_to_card(card) -> None:
    key = getattr(card.card_id, "name", None)
    if key is None:
        return
    entry = _load_overrides().get(key)
    if entry is None:
        return

    upgraded = bool(getattr(card, "upgraded", False))
    if upgraded and entry.get("upgraded_effect_vars"):
        for k, v in entry["upgraded_effect_vars"].items():
            card.effect_vars[k] = v
    elif not upgraded and entry.get("effect_vars"):
        for k, v in entry["effect_vars"].items():
            card.effect_vars[k] = v

    # Combat resolution reads card.base_damage / card.base_block (not
    # effect_vars), so numeric overrides must land there too.
    vars_for_state = (
        entry.get("upgraded_effect_vars") if upgraded else entry.get("effect_vars")
    ) or {}
    if "damage" in vars_for_state and hasattr(card, "base_damage"):
        card.base_damage = vars_for_state["damage"]
    if "block" in vars_for_state and hasattr(card, "base_block"):
        card.base_block = vars_for_state["block"]

    if not upgraded:
        if "cost" in entry:
            card.cost = entry["cost"]
            card.original_cost = entry["cost"]
        if "star_cost" in entry:
            card.star_cost = entry["star_cost"]
    if "card_type" in entry and hasattr(card, "card_type"):
        from sts2_env.core.enums import CardType

        try:
            card.card_type = CardType[entry["card_type"]]
        except KeyError:
            pass
    if "rarity" in entry and hasattr(card, "rarity"):
        from sts2_env.core.enums import CardRarity

        try:
            card.rarity = CardRarity[entry["rarity"]]
        except KeyError:
            pass
    if "keywords" in entry and hasattr(card, "keywords"):
        card.keywords = frozenset(entry["keywords"])
    for flag in (
        "can_be_generated_in_combat",
        "can_be_generated_by_modifiers",
        "gains_block",
        "has_turn_end_in_hand_effect",
    ):
        if flag in entry and hasattr(card, flag):
            try:
                setattr(card, flag, bool(entry[flag]))
            except AttributeError:
                # Read-only/derived properties (e.g. gains_block) can't be
                # overridden; they are computed from card behaviour.
                pass


_installed = False

# ---- 卡死防呆阈值(挂 seed 20000004 watchdog 实证,2026-09-05):----
# floor16 TransformCardsReward 22 候选宽状态,慢决策路径每次决策 85-143s、
# 反复 toggle 同一张牌不 confirm → 旧纯步数阈值(20 步)× ~90s ≈ 30min,
# 15min watchdog 先杀。改为「步数或墙钟任一先到」:快步路径行为不变
# (20 步先到),慢决策路径 120s 内强制解除,watchdog 不再背锅。
# 模块级常量:测试可 monkeypatch 阈值验证墙钟分支。
STUCK_CHOICE_MAX_STEPS = 20
STUCK_CHOICE_WALL_S = 120.0


def install_v01110_overrides() -> None:
    """Monkeypatch the simulator's card metadata choke point. Idempotent."""
    global _installed
    if _installed:
        return

    # 事件系统注册链:sts2_env.__init__ 不导入 sts2_env.events 包,导致
    # _EVENT_REGISTRY 空、所有 EVENT 房间只剩 "leave"。显式导入以触发
    # events/__init__.py 的 register_event(Act1/2/3+shared 68 个)。
    import sts2_env.events  # noqa: F401

    # ---- 药水击杀死锁不变式守卫(2026-09-04 注册,用户批准) ----
    # 根因:run_env._step_combat 药水分支直调 combat_now.use_potion()(不经
    # mgr.take_action);药水伤害击杀最后敌人时 CombatState.is_over=True,
    # 但转场 _resolve_combat_end() 只挂在 take_action 各 handler 尾部 →
    # phase 永卡 COMBAT,之后所有动作被 "No active combat." 挡回,空转到
    # 环境 10k 步截断(deadlock_trace 三级插桩 2/2 seed 同签名实证)。
    # 修复 = take_action 入口不变式:phase=COMBAT 且 combat.is_over 且
    # run 未终 → 补调转场。catch-all,覆盖所有绕过 handler 的直调路径。
    from sts2_env.run import run_manager as _rm_mod

    if not getattr(_rm_mod.RunManager, "_combat_end_repair", False):
        _orig_take_action = _rm_mod.RunManager.take_action

        def _take_action_combat_end_repair(self, action):
            if (self._phase == _rm_mod.RunManager.PHASE_COMBAT
                    and self._combat is not None and self._combat.is_over
                    and not self._run_state.is_over):
                return self._resolve_combat_end()
            return _orig_take_action(self, action)

        _take_action_combat_end_repair._is_repair = True
        _rm_mod.RunManager.take_action = _take_action_combat_end_repair
        _rm_mod.RunManager._combat_end_repair = True

    # ---- 药水击杀死锁修复·第二锚点(2026-09-05 死锁排查批,seed 实证) ----
    # 第一锚点把不变式补调挂在 take_action 入口,但实证复现(seed 20000174
    # 随机策略 1500 步空转,final_phase=COMBAT、hp=63、combat.is_over=True)
    # 证明 gym 环路根本到不了 take_action:run_env._step_combat 首行
    # `combat.is_over → return`(上游 run_env.py:474-476),后续每步都被
    # 这个裸 return 挡回,take_action 永不再被调用 → 第一锚点在该路径上
    # 是死代码,卡死照旧。修复 = 同一不变式补挂 _step_combat 入口(直调
    # 绕过点的正上一层):phase=COMBAT 且 combat.is_over 且 run 未终 →
    # 先补调 _resolve_combat_end 再走原逻辑。幂等:补调后 phase 离开
    # COMBAT,条件不再成立,不会重复触发。
    from sts2_env.gym_env.run_env import STS2RunEnv

    if not getattr(STS2RunEnv._step_combat, "_is_combat_end_repair", False):
        _orig_step_combat = STS2RunEnv._step_combat

        def _step_combat_combat_end_repair(self, action):
            mgr = self._mgr
            if (mgr is not None
                    and mgr._phase == _rm_mod.RunManager.PHASE_COMBAT
                    and mgr._combat is not None and mgr._combat.is_over
                    and not mgr.run_state.is_over):
                mgr._resolve_combat_end()
            return _orig_step_combat(self, action)

        _step_combat_combat_end_repair._is_combat_end_repair = True
        STS2RunEnv._step_combat = _step_combat_combat_end_repair

    # ---- 事件死锁修复:FakeMerchant 买不起的赝品仍 enabled(2026-09-05 探针实证) ----
    # 实证:seed 41300004,EVENT 层卡 60+ 步(progress guard 触发,
    # 死锁探针 dump 取证)。根因链:
    # FakeMerchant._fake_relic_option 无条件 enabled=True(act2.py:440-448),
    # 金币 < FAKE_RELIC_COST(50) 时 choose(buy_i) 返回 "Could not buy" 但
    # finished=False 且选项原样重挂(act2.py:503-523)→ 只看 mask 的确定性
    # 策略(训练侧/搜索式策略皆然)可以永远反复选同一买不起的选项,状态永不变。
    # 同库姊妹事件全部按「enabled=gold>=成本」惯例(act1.py:220 TeaMaster、
    # shared.py:2892/2901 EmotionalAwareness/ArachnidAcupuncture),本事件是
    # 漏网之鱼。修复 = 对齐惯例:金币不足时 buy_i 选项 enabled=False,
    # _actions_event 会过滤 disabled 选项(run_manager.py:1187-1193)→
    # 策略从根上选不到买不起的选项,卡死态不复存在。只影响付款不合法的
    # 状态,合法购买路径零变化。
    try:
        from sts2_env.events.act2 import FakeMerchant

        if not getattr(FakeMerchant._post_buy_options, "_is_gold_guard", False):
            _orig_post_buy = FakeMerchant._post_buy_options

            def _post_buy_options_gold_guard(self, run_state, inventory):
                options = _orig_post_buy(self, run_state, inventory)
                if run_state.player.gold < self.FAKE_RELIC_COST:
                    for opt in options:
                        if opt.option_id.startswith(self.BUY_OPTION_PREFIX):
                            opt.enabled = False
                return options

            _post_buy_options_gold_guard._is_gold_guard = True
            FakeMerchant._post_buy_options = _post_buy_options_gold_guard
    except Exception:
        import logging
        logging.getLogger(__name__).exception("FakeMerchant gold guard not installed")

    # power 注册链(与事件同款「谁 import 谁注册」陷阱):_POWER_CLASSES 只在
    # sts2_env.powers 包被导入时填充;缺注册时 Creature.apply_power 对未知
    # PowerId 静默降级(无实例写入)。生产入口经其他 import 链间接注册过,
    # 但裸构造链(测试/工具直接 import monsters)缺失 → FOGMOG 的
    # EyeWithTeeth 会丢失 MINION/ILLUSION。显式导入注册全部 267 powers。
    import sts2_env.powers  # noqa: F401

    import sts2_env.cards.factory as factory

    original = factory._apply_decompiled_static_metadata

    def patched(card):
        card = original(card)
        _apply_to_card(card)
        return card

    factory._apply_decompiled_static_metadata = patched

    # ---- 死亡兜底(环境层):玩家死但未终局时强制 lose_run ----
    # 卡死场景:hp=0 且处于 pending_choice(如 CARD_REWARD 选卡),run_env.step 只
    # 以 _mgr.is_over 为 terminated,而 _finalize_after_run_choice 在
    # pending_choice is not None 时不检查 is_dead → 永不完局、模型反复 choose 到
    # max_steps 截断(实测 seed 30500009 hp=0 卡 2000 步)。此处 monkeypatch
    # STS2RunEnv.step,在终止判定前补 is_dead → lose_run。
    import time as _time

    try:
        from sts2_env.gym_env.run_env import STS2RunEnv

        _orig_step = STS2RunEnv.step

        def _step_with_death_guard(self, action):
            obs, reward, terminated, truncated, info = _orig_step(self, action)
            mgr = self._mgr
            if mgr is None or mgr.run_state is None:
                return obs, reward, terminated, truncated, info
            rs = mgr.run_state

            # (1) 死亡兜底:玩家死但未终局 → lose_run(如死于非战斗 pending_choice)
            if not terminated and not truncated and rs.player.is_dead:
                rs.lose_run()
                terminated = True
                reward = -1.0

            # (2) 选卡/事件 multi-select 卡死防呆:同一 pending_choice 持续过久。
            #    模型反复 choose(toggle)不 confirm → 无限卡步(trace len=2000)。
            #    连续 20 步同 pending_choice 未变 → 自动 confirm(或放弃)。
            if not terminated and not truncated and rs.pending_choice is not None:
                key = id(rs.pending_choice)
                prev = getattr(self, "_stuck_choice_key", None)
                if prev != key:
                    self._stuck_choice_key = key
                    self._stuck_choice_count = 0
                    self._stuck_choice_t0 = _time.monotonic()
                else:
                    self._stuck_choice_count = getattr(self, "_stuck_choice_count", 0) + 1
                stuck_steps = getattr(self, "_stuck_choice_count", 0)
                stuck_wall = _time.monotonic() - getattr(
                    self, "_stuck_choice_t0", _time.monotonic())
                if (stuck_steps >= STUCK_CHOICE_MAX_STEPS
                        or stuck_wall >= STUCK_CHOICE_WALL_S):
                    if rs.pending_choice.can_confirm():
                        rs.resolve_pending_choice(None)  # 接受当前选择,正常结束
                    else:
                        rs.pending_choice = None  # 无法确认则放弃该选择(避免死锁)
                    self._stuck_choice_key = None

            # (3) 战斗内 multi-select 卡死防呆(2026-09-05 死锁探针批实证):
            #    与 (2) 同款病理的战斗层版本 —— seed 41300002/41300009,
            #    "Choose any number of hand cards to discard" 挂起期间模型反复
            #    choose(toggle)不 confirm,turn_count 恒 1、1200 步不终局
            #    (死锁探针 dump 取证)。
            #    连续 20 步同一 combat.pending_choice → 自动 confirm(或放弃)。
            if not terminated and not truncated and mgr._combat is not None:
                cpc = getattr(mgr._combat, "pending_choice", None)
                if cpc is None:
                    self._stuck_combat_choice_key = None
                else:
                    key = id(cpc)
                    prev = getattr(self, "_stuck_combat_choice_key", None)
                    if prev != key:
                        self._stuck_combat_choice_key = key
                        self._stuck_combat_choice_count = 0
                        self._stuck_combat_choice_t0 = _time.monotonic()
                    else:
                        self._stuck_combat_choice_count = \
                            getattr(self, "_stuck_combat_choice_count", 0) + 1
                    stuck_steps = getattr(self, "_stuck_combat_choice_count", 0)
                    stuck_wall = _time.monotonic() - getattr(
                        self, "_stuck_combat_choice_t0", _time.monotonic())
                    if (stuck_steps >= STUCK_CHOICE_MAX_STEPS
                            or stuck_wall >= STUCK_CHOICE_WALL_S):
                        if cpc.can_confirm():
                            mgr._combat.resolve_pending_choice(None)
                        else:
                            mgr._combat.pending_choice = None  # 放弃该选择防死锁
                        self._stuck_combat_choice_key = None
            return obs, reward, terminated, truncated, info

        STS2RunEnv.step = _step_with_death_guard
    except Exception:
        import logging
        logging.getLogger(__name__).exception("run_env death guard not installed")

    # ---- FOGMOG 终局判定(2026-09-02) —— primary 死亡时 minion 不阻断判胜 ----
    # 上游 `_check_combat_end` 胜利条件 = alive_enemies 空(含 minion)。FOGMOG 的
    # 召唤物 EyeWithTeeth 带 MINION+ILLUSION(死亡即满血复活),fogmog(主怪)死亡
    # 后 minion 永远在场 → 战斗永不结束 → run_env 201 回合上限强制判负。
    # 回合上限僵局取证:僵局的 FOGMOG 对局里 fogmog 均已 0 HP——纯环境假死锁。
    # C# 真实语义(CreatureCmd.cs:376 + Creature.IsSecondaryEnemy):primary
    # enemy 死亡时引擎将剩余 secondary enemies(MinionPower)全部 Kill → 判胜。
    # 此补丁对齐该语义:非 MINION 敌人全部死透(无存活、无 ILLUSION 复活中)
    # 即判胜;其余分支(玩家死亡/全灭/复活中 primary 阻断)走原实现不动。
    try:
        from sts2_env.core.combat import CombatState
        from sts2_env.core.enums import PowerId

        _orig_check_end = CombatState._check_combat_end

        def _check_combat_end_with_minion_semantics(self):
            _orig_check_end(self)
            if self.is_over or self.primary_player.is_dead:
                return
            if any(
                e.is_alive and PowerId.MINION not in e.powers for e in self.enemies
            ):
                return
            # primary 死体若在 ILLUSION 复活中(is_reviving)保持原语义:阻断判胜,
            # 等复活动作执行后继续战斗(Parafright 型;FOGMOG 的 eye 是 MINION,
            # 不进入本分支)。
            if any(
                (not e.is_alive)
                and any(bool(getattr(p, "is_reviving", False)) for p in e.powers.values())
                for e in self.enemies
                if PowerId.MINION not in e.powers
            ):
                return
            if any(e.is_alive for e in self.enemies):
                self._end_combat(player_won=True)

        CombatState._check_combat_end = _check_combat_end_with_minion_semantics
    except Exception:
        import logging
        logging.getLogger(__name__).exception("minion combat-end semantics not installed")

    # ---- RunState.relics 构造期别名冻结(2026-09-03) —— 拾取遗物全失效 ----
    # 上游 RunState.__init__ 做 "Primary-player compatibility aliases":
    #   self.relics = self.player.relics   ← 绑定当时那个 list 对象
    # 首场战斗构造时 CombatState._build_player_state 执行
    #   player_state.relics = self._normalize_relic_ids(relics)  ← 重绑新 list
    # 此后一切拾取(Vajra/宝箱/精英/商店/事件/boss 遗物)append 到新 list,
    # rs.relics 永远冻结在起始遗物。受害面:
    #   ① run_manager._setup_combat / _enter_event_combat 传
    #      relics=list(rs.relics)(陈旧)→ _build_player_state 的
    #      `if relics:` 分支把 player.relics 重置回 [CRACKED_CORE]
    #      → 每场战斗开打前拾取遗物全部被抹掉、遗物效果从不生效
    #      (模拟器语义 = 「STS 减遗物系统」,比观测缺失严重一级);
    #   ② run_env 基础 151 维 obs 的遗物计数(run_env.py:714)整局恒 1;
    #   ③ obs_v2 289 维遗物块(_encode_relics 读 rs.relics)整局恒起始遗物;
    #   ④ 战斗遥测记录器 extract_entry 的 relics 字段(2345 行语料实测恒
    #      CRACKED_CORE,因此判「遗物零方差不入特征」)。
    # 修复 = 把别名改成活 property(读 = player.relics,写 = 转发 player),
    # __init__ 的别名赋值经 setter 写回 player.relics(同对象,无副作用);
    # init 之外无任何 rs.relics 写入方(grep 已核),relic_grab_bag 别名无读者
    # (PlayerState.populate_relic_grab_bag 会重绑,故不在此修)。
    try:
        from sts2_env.run.run_state import RunState

        def _relics_getter(self):
            return self.player.relics

        def _relics_setter(self, value):
            self.player.relics = value

        RunState.relics = property(_relics_getter, _relics_setter)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("RunState.relics live alias not installed")

    _installed = True


# Public-build alias: without the (maintainer-environment) numeric override
# table, installing this applies the engine-level fixes only.
install_engine_fixes = install_v01110_overrides
