"""Combat 侧修复锁测试(败场钩子/随机目标/终局判定/首回合置底/minion 终局)。

每项测试 docstring 记录三段式核对链:Python 现状 → C# 原文(文件:行号) → 修法。
C# 权威参照:本仓库 decompiled/ 目录(v0.111.0,只读反编译源)。

- 败场不触发 after_combat_end(CombatManager.cs:1277-1286 vs 1318/1329)。
- 随机目标禁重复命中(AttackCommand.cs:322/557-563/607-619)。
- _check_combat_end 调用密度对齐 C# 固定节点(CombatManager.cs
  830/847/1089/1429/1560/1579/1591 + ActionExecutor.cs:161-171)。
- 首回合 ShouldStartAtBottomOfDrawPile 置底(CombatManager.cs:908-923,
  EnchantmentModel.cs:125, Imbued.cs:9)。
- minion 终局 patch 窄缝锁测试(patch.py:326-349,只加测试不改产品码)。
"""

from __future__ import annotations

import pytest

from sts2_env.cards.base import reset_instance_counter
from sts2_env.cards.ironclad_basic import create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import CombatSide, PowerId
from sts2_env.core.rng import Rng
from sts2_env.monsters.act1_weak import create_shrinker_beetle


# ---------------------------------------------------------------- helpers

def _mk_combat(enemy_count: int = 2):
    """最小 combat:铁甲初始牌组 + N 只 shrinker beetle(无特殊 power)。"""
    reset_instance_counter()
    rng = Rng(42)
    combat = CombatState(
        player_hp=80, player_max_hp=80, deck=create_ironclad_starter_deck(), rng_seed=42
    )
    for _ in range(enemy_count):
        creature, ai = create_shrinker_beetle(rng)
        combat.add_enemy(creature, ai)
    combat.start_combat()
    return combat


class _ProbeRelic:
    """Duck-typed relic 探针:记录全部 hook 调用;未显式给 action 的 hook 原子化 no-op。

    hooks 分发对 relic 是无条件鸭子调用(hooks.py _iter_relic_listeners →
    relic.<hook>(...)),返回 None 对所有值型 hook(should_*/modify_*)等价
    "无修改/默认语义",对本文件覆盖的回合流足够。
    """

    enabled = True

    def __init__(self, hooks: dict | None = None):
        object.__setattr__(self, "_hooks", dict(hooks or {}))
        object.__setattr__(self, "calls", [])

    def __getattr__(self, name: str):
        hooks = object.__getattribute__(self, "_hooks")
        calls = object.__getattribute__(self, "calls")

        def _hook(*args, **kwargs):
            calls.append(name)
            fn = hooks.get(name)
            if fn is not None:
                return fn(*args, **kwargs)

        return _hook

    def count(self, name: str) -> int:
        return object.__getattribute__(self, "calls").count(name)


# ------------------------------------------------- 败场不触发 after_combat_end

class TestF5LossSkipsAfterCombatEnd:
    """败场不触发 after_combat_end。

    Python 现状:_end_combat 不分胜负先 fire_after_combat_end(combat.py
    原 3868-3872 一带),胜场再加 fire_after_combat_victory。
    C# 权威:Hook.AfterCombatEnd 只在 EndCombatInternal(CombatManager.cs:1318)
    触发,而它只被胜利路径 CheckWinCondition→IsCombatEnding(1390-1403)调用;
    败场 ProcessPendingLoss(CombatManager.cs:1277-1286)只置 IsInProgress=False
    并发 CombatEnded 事件,不走 AfterCombatEnd/AfterCombatVictory。
    修法:_end_combat 按胜负门控,胜场才 fire(玩家死后 run 随即结束,
    败场无任何监听者副作用需求——全部实现者是计数/清理类,见 relics/common.py
    CentennialPuzzle 等)。
    """

    def test_win_fires_after_combat_end_and_victory(self):
        combat = _mk_combat(2)
        probe = _ProbeRelic()
        combat.relics.append(probe)
        a, b = combat.enemies
        combat.kill_creature(a)
        assert not combat.is_over
        combat.kill_creature(b)
        assert combat.is_over and combat.player_won
        assert probe.count("after_combat_end") == 1
        assert probe.count("after_combat_victory") == 1
        assert probe.count("after_combat_victory_early") == 1

    def test_loss_fires_nothing(self):
        combat = _mk_combat(2)
        probe = _ProbeRelic()
        combat.relics.append(probe)
        combat.primary_player.current_hp = 0
        combat._check_combat_end()
        assert combat.is_over and not combat.player_won
        assert probe.count("after_combat_end") == 0
        assert probe.count("after_combat_victory") == 0
        assert probe.count("after_combat_victory_early") == 0

    def test_loss_end_state_idempotent_run_end_path_unobstructed(self):
        """败场后重复 check 不再触发任何钩子,is_over/player_won 稳定
        ——run 侧 _resolve_combat_end 以这两个标志收尾,不受门控影响。"""
        combat = _mk_combat(1)
        probe = _ProbeRelic()
        combat.relics.append(probe)
        combat.primary_player.current_hp = 0
        combat._check_combat_end()
        combat._check_combat_end()
        combat._end_combat(player_won=False)
        assert combat.is_over and not combat.player_won
        assert probe.count("after_combat_end") == 0


# ---------------------------------------------- 随机目标禁重复命中

class TestF10RandomTargetNoDuplicates:
    """随机目标"禁止重复命中"语义。

    Python 现状:effects.py deal_damage_to_random_enemy 每跳从全体 hittable
    重抽,无禁重复参数(允许重复)。
    C# 权威:AttackCommand.TargetingRandomOpponents(state, allowDuplicates=true)
    (AttackCommand.cs:322);每跳先取存活候选,空则 break(557-563);
    allowDuplicates=false 时从本攻击已命中结果(_results 的 Receiver)排除后
    再抽,剔空则抛 InvalidOperationException(607-619)。
    修法:函数加 allow_duplicates 参数(默认 True=现状零变化);反编译树全量
    grep 证实当前无任何调用方传 False(8 处 TargetingRandomOpponents 全走
    默认),故无卡牌需要接线;禁重复模式语义(排除已命中/剔空抛错/无存活
    break)按 C# 原文逐条对齐。
    """

    def _mk(self, enemy_count: int):
        return _mk_combat(enemy_count)

    def test_default_allows_repeats_and_consumes_rng_per_hit(self):
        combat = self._mk(1)
        enemy = combat.enemies[0]
        from sts2_env.cards.effects import deal_damage_to_random_enemy

        before = combat.combat_targets_rng.counter
        results = deal_damage_to_random_enemy(
            combat, combat.player, base_damage=0, hits=5
        )
        assert len(results) == 5
        assert all(r.target is enemy for r in results)
        assert combat.combat_targets_rng.counter - before == 5

    def test_no_duplicates_hits_each_enemy_at_most_once(self):
        combat = self._mk(3)
        from sts2_env.cards.effects import deal_damage_to_random_enemy

        before = combat.combat_targets_rng.counter
        results = deal_damage_to_random_enemy(
            combat, combat.player, base_damage=0, hits=3, allow_duplicates=False
        )
        targets = {id(r.target) for r in results}
        assert len(results) == 3
        assert len(targets) == 3
        assert combat.combat_targets_rng.counter - before == 3

    def test_no_duplicates_exhausted_pool_raises_like_csharp(self):
        """段数>敌数:C# 在存活目标全被命中后抛 InvalidOperationException
        (AttackCommand.cs:612-615),Python 对齐为 ValueError。"""
        combat = self._mk(3)
        from sts2_env.cards.effects import deal_damage_to_random_enemy

        with pytest.raises(ValueError):
            deal_damage_to_random_enemy(
                combat, combat.player, base_damage=0, hits=4, allow_duplicates=False
            )

    def test_no_duplicates_with_no_alive_targets_breaks_silently(self):
        """C# 每跳存活候选为空 → break 不抛(AttackCommand.cs:557-563),
        禁重复模式同样走该回退。"""
        combat = self._mk(2)
        from sts2_env.cards.effects import deal_damage_to_random_enemy

        for enemy in list(combat.enemies):
            combat.kill_creature(enemy)
        assert combat.is_over  # 全灭判胜先发生
        before = combat.combat_targets_rng.counter
        results = deal_damage_to_random_enemy(
            combat, combat.player, base_damage=0, hits=3, allow_duplicates=False
        )
        assert results == []
        assert combat.combat_targets_rng.counter - before == 0


# ------------------------------- 终局判定调用密度对齐 C# 固定节点

class TestF11CheckCombatEndNodeAlignment:
    """删除 C# 不存在的 4 个中途 _check_combat_end 调用点。

    Python 现状(改动前):start/end 回合流的每个子阶段后都调
    _check_combat_end,比 C# 密——极端情形提前一拍结束战斗。
    C# 权威节点集(全量 grep + 逐点核对):
      - StartTurn 玩家侧尾        CombatManager.cs:830
      - StartTurn 敌方侧尾        CombatManager.cs:847
      - EndEnemyTurn 尾           CombatManager.cs:1089
      - ExecuteEnemyTurn 每敌后    CombatManager.cs:1429
      - EndPlayerTurnPhaseOne×3   CombatManager.cs:1560/1579/1591
      - (PhaseTwo 无检查)          CombatManager.cs:1741-1778
      - 逐动作检查(全局兜底)      ActionExecutor.cs:161-171
    被删调用点清单(各对应 C# 无检查的窗口):
      1. _continue_player_turn_setup 每玩家 orb AfterTurnStart 后(原 combat.py:1014)
         → C# SetupPlayerTurn/RunAutoPrePlayPhase 派发中途无检查,唯一节点在
         全部启动 hook 后(cs:830)。
      2. end_player_turn 每玩家 orb BeforeTurnEnd 后(原 :1594)
         → C# DoTurnEnd(1602-1628)中途无检查,节点在其后(cs:1579)。
      3. end_player_turn 玩家 after_turn_end 派发后(原 :1606)
         → C# PhaseTwo(AfterSideTurnEnd)无检查(1741-1778),下一节点在敌方
         StartTurn 尾(cs:847)。
      4. _finish_enemy_turn 敌方 before_turn_end 派发后(原 :1774)
         → C# EndEnemyTurnInternal(1691-1700)中途无检查,唯一节点在
         EndEnemyTurn 尾(cs:1089)。
    保留:play_card/use_potion/deal_damage/kill_creature/escape/auto_play/
    resolve_choice 内的检查 = C# ActionExecutor.cs:161-171 逐动作检查的对应物。
    卡死回归:删除点死亡均由后续固定节点捕获(下方两条窗口测试 + 全量套件)。
    """

    def test_kill_in_player_after_turn_end_window_caught_by_enemy_start_node(self):
        """玩家 after_turn_end 派发中杀死末敌(删除点 3 的窗口)
        → 敌方回合开始节点(combat.py:1731 ↔ CombatManager.cs:847)捕获判胜,
        end_player_turn 正常返回,不卡死。"""
        combat = _mk_combat(2)
        a, b = combat.enemies
        combat.kill_creature(a)

        def _kill_last(owner, side, combat_state):
            if side == CombatSide.PLAYER:
                b.current_hp = 0

        probe = _ProbeRelic({"after_turn_end": _kill_last})
        combat.relics.append(probe)
        combat.end_player_turn()
        assert combat.is_over
        assert combat.player_won

    def test_kill_in_enemy_before_turn_end_window_caught_by_end_enemy_turn_node(self):
        """敌方 before_turn_end 派发中最后一个敌人死亡(删除点 4 的窗口)
        → EndEnemyTurn 尾节点(combat.py:1781 ↔ CombatManager.cs:1089)捕获
        判胜,_finish_enemy_turn 正常返回,不卡死。

        直驱 _finish_enemy_turn(被删检查的所在函数),不走完整
        end_player_turn:敌方面板 move 会触发与窗口无关的数值型 relic hook
        (modify_power_amount_* 需要 int 返回),探针 duck-type 无法通用兜底。"""
        combat = _mk_combat(2)
        a, b = combat.enemies
        combat.kill_creature(a)

        def _kill_self(owner, side, combat_state):
            # relic 监听者的 owner 恒为持有者(玩家),这里只按 side 门控
            if side == CombatSide.ENEMY:
                b.current_hp = 0

        probe = _ProbeRelic({"before_turn_end_very_early": _kill_self})
        combat.relics.append(probe)
        combat._finish_enemy_turn()
        assert combat.is_over
        assert combat.player_won
        assert probe.count("before_turn_end_very_early") >= 1
        assert probe.count("after_turn_end") >= 1


# --------------------------------------- 首回合抽牌附魔置底

class TestF12ImbuedStartsAtBottomOfDrawPile:
    """首回合抽牌先做附魔置底,再做 innate 移顶。

    Python 现状:_prepare_opening_draw_for_owner(combat.py 原 1023-1036)只
    实现 innate(移顶 + max + clamp),无置底逻辑。
    C# 权威:CombatManager.cs:908-923 —— TurnNumber==1 时先把
    Enchantment.ShouldStartAtBottomOfDrawPile 卡逐张 MoveToBottomInternal
    (保序落底),再对 Innate 卡 Except(置底卡) MoveToTopInternal,
    handDraw=max(handDraw, innate数) 且 clamp ≤ MaxCardsInHand(10);
    EnchantmentModel.cs:125 基类默认 False,反编译树唯一覆盖者 = Imbued
    (Imbued.cs:9)。
    修法:enchantments.py 增加 SHOULD_START_AT_BOTTOM_OF_DRAW_PILE 标志表 +
    should_start_at_bottom_of_draw_pile(card);combat.py 置底→innate 移顶
    严格按 C# 顺序。无标记卡行为逐位不变(置底集为空时公式退化为原式)。
    """

    def _mk_started(self):
        return _mk_combat(1)

    def _craft_draw_order(self, combat, order):
        """把全部卡按给定顺序摆进 draw(清空 hand/discard),返回实例列表。"""
        state = combat.current_player_state
        cards = [c for pile in (state.hand, state.draw, state.discard) for c in pile]
        assert len(cards) == len(order)
        for card in cards:
            card.owner = combat.player
            if card in state.hand:
                state.hand.remove(card)
            if card in state.discard:
                state.discard.remove(card)
            if card in state.draw:
                state.draw.remove(card)
        lookup = list(order)
        state.hand.clear()
        state.discard.clear()
        state.draw[:] = lookup
        return lookup

    def test_marked_card_lands_at_bottom_innate_on_top(self):
        from sts2_env.cards.enchantments import should_start_at_bottom_of_draw_pile

        combat = self._mk_started()
        state = combat.current_player_state
        cards = [c for pile in (state.hand, state.draw, state.discard) for c in pile]
        marked = cards[0]
        innate_plain = cards[1]
        plain = cards[2]
        marked.add_enchantment("Imbued")
        innate_plain.keywords = frozenset(innate_plain.keywords) | {"innate"}
        assert should_start_at_bottom_of_draw_pile(marked)
        assert not should_start_at_bottom_of_draw_pile(plain)

        self._craft_draw_order(combat, [plain, marked, innate_plain, *cards[3:]])
        ret = combat._prepare_opening_draw_for_owner(combat.player, 5)
        # innate(排除置底卡)只有 1 张 → max(5, 1) = 5
        assert ret == 5
        assert state.draw[0] is innate_plain            # innate 移顶
        assert state.draw[-1] is marked                 # 附魔卡置底
        assert marked not in state.draw[:-1]

    def test_innate_and_marked_card_goes_bottom_not_top(self):
        """C# list2 = Innate.Except(置底集)(CombatManager.cs:916):
        同时带 innate 与 Imbued 的卡只置底,不进 innate 移顶集。"""
        combat = self._mk_started()
        state = combat.current_player_state
        cards = [c for pile in (state.hand, state.draw, state.discard) for c in pile]
        both = cards[0]
        both.add_enchantment("Imbued")
        both.keywords = frozenset(both.keywords) | {"innate"}
        self._craft_draw_order(combat, list(cards))
        ret = combat._prepare_opening_draw_for_owner(combat.player, 5)
        assert ret == 5                    # 不计入 innate 数
        assert state.draw[-1] is both      # 置底
        assert all(not c.is_innate for c in state.draw[:-1])

    def test_unmarked_behavior_bit_identical_to_previous_formula(self):
        """无标记卡:结果 == innate + non_innate(原实现公式),逐位一致。"""
        combat = self._mk_started()
        state = combat.current_player_state
        cards = [c for pile in (state.hand, state.draw, state.discard) for c in pile]
        cards[0].keywords = frozenset(cards[0].keywords) | {"innate"}
        cards[1].keywords = frozenset(cards[1].keywords) | {"innate"}
        before = list(cards)
        expected = [c for c in before if c.is_innate] + [
            c for c in before if not c.is_innate
        ]
        self._craft_draw_order(combat, before)
        ret = combat._prepare_opening_draw_for_owner(combat.player, 5)
        assert state.draw == expected
        assert ret == min(10, max(5, 2))

    def test_round_other_than_one_untouched(self):
        combat = self._mk_started()
        state = combat.current_player_state
        cards = [c for pile in (state.hand, state.draw, state.discard) for c in pile]
        cards[0].add_enchantment("Imbued")
        self._craft_draw_order(combat, list(cards))
        combat.round_number = 2
        assert combat._prepare_opening_draw_for_owner(combat.player, 5) == 5
        assert state.draw == cards

    def test_end_to_end_marked_card_never_in_opening_hand(self):
        """真实 start_combat 路径:Imbued 卡置底后必不进开局手牌
        (修复前随机洗牌可能开局摸到它);随后被 Imbued 既有 round-1
        auto-play 逻辑消费,不再停留在抽牌堆。"""
        deck = create_ironclad_starter_deck()
        marked = deck[3]
        marked.add_enchantment("Imbued")
        reset_instance_counter()
        combat = CombatState(
            player_hp=80, player_max_hp=80, deck=deck, rng_seed=42
        )
        creature, ai = create_shrinker_beetle(Rng(7))
        combat.add_enemy(creature, ai)
        combat.start_combat()
        state = combat.current_player_state
        assert marked not in state.hand
        assert marked not in state.draw  # 已被 round-1 auto-play 消费
        assert any(
            marked in pile for pile in (state.discard, state.play, state.exhaust)
        )


# ------------------------------------------------ minion 终局窄缝锁测试

@pytest.fixture
def bug2c_patch():
    """确保 minion 终局 patch 已安装(与套件内 fogmog 等既有用例同一惯例)。

    install_v01110_overrides 是进程级幂等安装(_installed 守卫,不提供卸载);
    全量 gated 套件里它在本文件之前已被 test_act1_victory_semantics 装上,
    因此本文件全部用例都必须在 base 与 patched 两种
    _check_combat_end 下同样成立——它们的断言均不依赖 minion 语义,天然兼容。
    """
    from sts2_env.datawash.patch import install_v01110_overrides

    install_v01110_overrides()
    yield


class _BlockingFakePower:
    """should_stop_combat_ending=True 且无 is_reviving 属性的 mock power
    (getattr(p, "is_reviving", False) → False,patched 分支不认它)。
    after_combat_* no-op:hook 分发对 power 是无鸭子检查直调,提前判胜路径
    会在 fire_after_combat_* 上触到本实例。"""

    def should_stop_combat_ending(self) -> bool:
        return True

    def after_combat_end(self, owner, combat) -> None:
        pass

    def after_combat_victory(self, owner, combat) -> None:
        pass

    def after_combat_victory_early(self, owner, combat) -> None:
        pass


class TestF13Bug2cPatchNarrowSeam:
    """minion 终局 patched 分支的窄缝不变式锁测试(只加测试)。

    Python 现状:patch.py:326-349 重写 _check_combat_end,"primary 死体阻断
    判胜"只查 p.is_reviving;基版 combat.py _check_combat_end 的
    blocking_dead_enemies 认全部 should_stop_combat_ending。
    C# 权威:IsCombatEnding(CombatManager.cs:417-436)= 无存活 primary 且
    !Hook.ShouldStopCombatFromEnding(Hook.cs:2451-2461 对全部监听者求票,
    不区分死活/是否 MINION);即 C# 尊重全部 should_stop 票。
    修法:锁定当前内容集下的隐式不变式——同步出怪型 blocker(INFESTED 族,
    死后同步补位非 MINION 敌人)状态下 patched 与基版一致(都不提前判胜)。
    """

    def test_sync_replacement_spawns_block_patched_win(self, bug2c_patch):
        """INFESTED 族同步补位:死体 blocker 出 4 只非 MINION wriggler
        → patched 首道"存活非 MINION"检查照样阻断,不提前判胜。"""
        from sts2_env.powers.monster import InfestedPower

        reset_instance_counter()
        rng = Rng(42)
        combat = CombatState(
            player_hp=80, player_max_hp=80, deck=create_ironclad_starter_deck(),
            rng_seed=42,
        )
        host, host_ai = create_shrinker_beetle(rng)
        combat.add_enemy(host, host_ai)
        combat.start_combat()
        host.powers[PowerId.INFESTED] = InfestedPower(1)
        assert combat.kill_creature(host)
        # after_death 同步补位:4 只 wriggler 存活且非 MINION
        alive = combat.alive_enemies
        assert len(alive) == 4
        assert all(PowerId.MINION not in e.powers for e in alive)
        combat._check_combat_end()
        assert not combat.is_over  # 基版/patched 一致:不判胜

    @pytest.mark.xfail(strict=True, reason=(
        "窄缝实证(2026-09-07):patch.py:326-349 的死亡阻断只认 "
        "is_reviving;构造 should_stop_combat_ending=True 且 is_reviving=False "
        "的死体 + 唯一活敌为 MINION 时,patched 提前判胜(is_over=True,"
        "player_won=True),基版(存活 MINION 使 alive_enemies 非空)与 C#"
        "(IsCombatEnding 先问 Hook.ShouldStopCombatFromEnding,对全部监听者"
        "求票,CombatManager.cs:417-436 + Hook.cs:2451-2461)都不判胜。当前"
        "内容不可达(全部 blocker 的死后结算要么同步出非 MINION 补位、要么置 "
        "is_reviving),现约定不改 patch.py,以 strict xfail 钉死证据:"
        "若将来修 patch.py 使其尊重 should_stop_combat_ending,本用例 "
        "XPASS→失败,提示移除。"
    ))
    def test_blocker_corpse_with_alive_minion_early_wins_in_patched(self, bug2c_patch):
        """窄缝构造(死体 blocker[is_reviving=False] + 唯一活敌 MINION):
        期望(C#/基版语义)= 不提前判胜;patched 实际提前判胜 → xfail。"""
        reset_instance_counter()
        rng = Rng(42)
        combat = CombatState(
            player_hp=80, player_max_hp=80, deck=create_ironclad_starter_deck(),
            rng_seed=42,
        )
        corpse, corpse_ai = create_shrinker_beetle(rng)
        combat.add_enemy(corpse, corpse_ai)
        from sts2_env.monsters.act1 import create_eye_with_teeth

        eye, eye_ai = create_eye_with_teeth(rng)
        combat.add_enemy(eye, eye_ai)
        combat.start_combat()
        corpse.powers[PowerId.STRENGTH] = _BlockingFakePower()
        corpse.current_hp = 0  # 死体(绕过 kill_creature,保持 blocker 在身上)
        eye.current_hp = 6
        combat._check_combat_end()
        # C# IsCombatEnding(CombatManager.cs:417-436)语义:存在
        # should_stop_combat_ending 票 → 不终局
        assert not combat.is_over
