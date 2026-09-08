"""Run 侧 4 项修复锁测试（RNG 具名流接线 / boss 遗物池对账+宝箱流 / 战后治疗 / DoubleBoss）。

每项修复附"三段式核对"（Python 现状 → C# 原文 文件:行号 → 修法）。
C# 权威 = 本仓库 decompiled/ 目录（v0.111.0 反编译源）。

============================================================================
RunManager 私有 RNG 流接线对齐 C# 具名流
============================================================================
【Python 现状（修复前）】run_manager.py:239 `self._rng = Rng(seed + 9999)` 是
C# 不存在的私有流；:536/:597 每场战斗抽 `combat_seed`、:568 进房 `choice(pool)`
选 encounter、:569/:616 造 `Rng(私有流抽取)` 当 encounter setup rng——同一游戏
seed 下与原版各流消耗序列断链（此前审计结论）。

【C# 原文】
- Entities.Rngs/RunRngType.cs:3-17：12 条具名 run 流（UpFront/Shuffle/
  UnknownMapPoint/CombatCardGeneration/CombatPotionGeneration/
  CombatCardSelection/CombatEnergyCosts/CombatTargets/MonsterAi/Niche/
  CombatOrbs/TreasureRoomRelics）。
- Runs/RunRngSet.cs:157-161 `CreateRng(rngType)` =
  `new Rng(Seed, StringHelper.SnakeCase(rngType.ToString()))`；
  Random/Rng.cs:59-62 `Rng(ulong seed, string name)` =
  `seed + StringHelper.GetDeterministicHashCode(name)`（流名种子派生公式）。
- encounter 选择走 UpFront：Runs/RunManager.cs:756
  `act.GenerateRooms(State.Rng.UpFront, ...)`；Models/ActModel.cs:331-387
  GenerateRooms 内 `_rooms.Boss = rng.NextItem(AllBossEncounters)` 等——
  遭遇在地图生成期从 UpFront 选定烤进 RoomSet；进房 PullNextEncounter
  （ActModel.cs:445-452）按 RoomSet 游标轮转（RoomSet.cs:70-86），不再抽流。
- 战斗级种子：C# 无"进战斗抽种子"一环。CombatState.cs:127
  `monster.RunRng = RunState.Rng`（整组流引用）+ CombatState.cs:136
  per-creature rng = `new Rng((uint)((RunState.Rng.Seed + CurrentMapCoord?.col)
  ?? ... ?? (CurrentActIndex + CombatId)))` 公式派生（已接线）。
- encounter setup 随机（出怪组成/HP 变体）：CombatState.cs:132
  `SetUniqueMonsterHpValue(creaturesOnSide, RunState.Rng.Niche)`、
  Creature.cs:303-315 —— HP 变体走 Niche 流；RunRngSet.cs:137-140 Niche =
  "niche one-off RNG stuff"。

【修法】删除私有流与 RUN_MANAGER_RNG_SEED_OFFSET；encounter 选择消费
`run_state.rng.up_front`（流对齐；"地图期烘焙 vs 进房选择"的结构差记录于
此前审计，不属本次）；encounter setup rng 直传 `run_state.rng.niche`（共享单
流，对齐 C# 出怪随机走 run 级流的语义）；combat_seed 抽取删除，
`rng_seed=0` 仅作 CombatState 无 run 上下文兜底占位（有 run 上下文时被
公式派生覆盖）。已知偏差（记录）：Python setup 链把"遭遇内组成选择+HP roll"
合用 Niche，C# 组成在 EncounterModel 内静态确定、Niche 只承担 HP 变体且带
同侧去重（内容缺口，已记录不实施）。

============================================================================
boss 遗物池对账（并宝箱遗物流接线）—— 对账结论 = 审计前提有误，不实施池改写
============================================================================
【Python 现状】run_manager.py 硬编码 `_BOSS_RELIC_POOL`（11 项 STS1 boss 遗物
名），剔除已持有后 shuffle 取前 3。

【C# 原文（逐文件核对 v0.111.0）】
- Rewards/RewardsSet.cs:88-91 `WithRewardsFromRoom`：最终幕 boss
  （CurrentActIndex >= Acts.Count - 1）直接返回空奖励集；
- Rewards/RewardsSet.cs:222-239 `GenerateRewardsFor`：Boss 房奖励 = GoldReward
  + RollForPotionAndAddTo + CardReward，**无 RelicReward**（Elite 房才有）；
- Entities.Relics/RelicRarity.cs：枚举无 Boss 值（None/Starter/Common/
  Uncommon/Rare/Shop/Event/Ancient）；本池 11 遗物在 C# 全部是
  RelicRarity.Ancient（如 Astrolabe.cs:14），Python relics registry 亦标
  ANCIENT/pool=EVENT；
- Runs/RelicGrabBag.cs:13-18 `_rarities = {Common, Uncommon, Rare, Shop}`，
  ancient 遗物从不进 grab bag（无"boss 池加权 grab-bag"可言）；
- 此前审计所指 Entities.TreasureRelicPicking（RelicPickingFight.cs 一族）+
  Runs/RunManager.cs:486 TreasureRoomRelicSynchronizer = 多人宝藏箱抢遗物
  小游戏，与 boss 奖励无关。

【修法】按对账纪律（审计判断有误时不硬修）：池组成/均匀抽取维持 Python 训练
环境自有语义（STS1 式三选一），不伪照不存在的 C# 流程；仅 RNG 接线对齐——
宝箱抽取改走 run 级 TreasureRoomRelics 具名流（RunRngSet.cs:93
`TreasureRoomRelics => GetRng(RunRngType.TreasureRoomRelics)`；CreateRng
SnakeCase 流名 = "treasure_room_relics"，Python RunRngSet.treasure_room 同名）。

============================================================================
战后治疗改 BURNING_BLOOD/BLACK_BLOOD 持有校验（遗物驱动）
============================================================================
【Python 现状（修复前）】run_manager.py `_CHARACTER_CONFIG` ironclad
`heal_after_combat: 6` → 胜场按常数治疗且不校验遗物仍在；叠加
relics/starter.py BurningBlood.after_combat_victory(+6) 后实际双倍 +12。

【C# 原文】
- Models.Relics/BurningBlood.cs:14 CanonicalVars = `new HealVar(6m)`；
  :16-23 `AfterCombatVictory(CombatRoom _)` → `if (!Owner.Creature.IsDead)
  CreatureCmd.Heal(Owner.Creature, Heal.BaseValue)`；
- Models.Relics/BlackBlood.cs:14 `new HealVar(12m)`，:16-23 同钩子；
- 触发点：Combat/CombatManager.cs:1318 `await Hook.AfterCombatEnd(...)` 后
  :1329 `await Hook.AfterCombatVictory(runState, combatState, room)` ——
  只在胜利路径 EndCombatInternal 触发；遗物被换掉即无此监听者，不再治疗。

【修法】删除 config 常数与 `_heal_after_combat` 治疗块（死路径清除）；治疗
唯一来源 = combat 胜场钩子（Python `_end_combat` → `fire_after_combat_victory`
→ BurningBlood +6 / BlackBlood +12），随 HP 同步回写 run 侧。
结果 dict 的 "healed" 键保留但恒 0（combat.is_over 后 run 侧无法观测 hook 前
HP；无外部消费方，grep 验证）。

============================================================================
DoubleBoss 进阶（最终幕双 boss 连战）
============================================================================
【Python 现状（修复前）】map/acts.py `ALL_ACTS` 3 幕，ActMap 无 second boss
概念；run_state.py:1457/1582 已有 `has_double_boss = asc >= 10` 挂位（无消费）。

【C# 原文】
- Entities.Ascension/AscensionLevel.cs:3-16：DoubleBoss = 第 10 级（末位）；
  AscensionManager.cs:44-47 `HasLevel(level)` = `_level >= (int)level`；
- Runs/RunManager.cs:761-764：仅最后一幕
  （i == State.Acts.Count - 1）且 HasLevel(DoubleBoss) 时
  `secondBossEncounter = State.Rng.UpFront.NextItem(act.AllBossEncounters
  .Where(e => e.Id != act.BossEncounter.Id))` → `act.SetSecondBossEncounter`；
- Map/StandardActMap.cs:94-99：BossMapPoint = (col/2, rowCount)，
  hasSecondBoss 时 SecondBossMapPoint = (col/2, rowCount + 1)；
  :226-228 `BossMapPoint.AddChildPoint(SecondBossMapPoint)`；
  :303-305 `SecondBossMapPoint.PointType = MapPointType.Boss`；
- Map/ActMap.cs:70-89 GetPoint 解析序 Boss → SecondBoss → Starting → Grid；
- Rooms/RoomSet.cs:76-86 `NextBossEncounter`：bossEncountersVisited != 0 且
  SecondBoss 非空 → SecondBoss（即第一场出 Boss、第二场出 SecondBoss）；
- Combat/CombatManager.cs:1335-1338：WinTime 仅当
  （SecondBossMapPoint 非空 && 当前坐标 == SecondBossMapPoint）或
  （SecondBossMapPoint 为空 && 当前坐标 == BossMapPoint）——双 boss 下必须
  打赢第二场才算通关（AutoSlayer.cs:219 同判据：第一场 boss 后继续导航）。

【修法】ActMap 增加 second_boss_point（不入 _grid 的 meta 节点，_center_grid
后按 boss 实际列 +1 行创建，不消耗 RNG → 进阶 0 地图逐位不变）；
ActMap.get_point 补 C# 同款解析序；RunState.generate_map 仅最终幕且
has_double_boss 时挂节点；RunManager 进 second_boss_point 房时从 boss 池
剔除第一场 boss（up_front 选择，对齐 RunManager.cs:763 语义）；
_after_card_reward 在"第二 boss 未打"时回 MAP_CHOICE 而非 boss 遗物/换幕；
第二场胜利后走原 boss 遗物 → 换幕 → 通关路径。
"""

from __future__ import annotations

import pytest

from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import RoomType
from sts2_env.core.rng import Rng, deterministic_hash_code
from sts2_env.map.generator import ActMap, generate_act_map
from sts2_env.map.map_point import MapCoord
from sts2_env.monsters.act1_weak import create_shrinker_beetle
from sts2_env.relics.base import RelicId, RelicRarity
from sts2_env.relics.registry import RELIC_REGISTRY, load_all_relics
from sts2_env.run.run_manager import (
    RunManager,
    _BOSS_RELIC_POOL,
    _CHARACTER_CONFIG,
)
from sts2_env.run.run_state import RunRngSet, RunState

UINT_MASK = 0xFFFFFFFF


def _uint32(v: int) -> int:
    return v & UINT_MASK


# ---------------------------------------------------------------------------
# 驱动工具：全自动走完房间/奖励链（仅测试用）
# ---------------------------------------------------------------------------

_MAX_DRIVER_STEPS = 400


def _win_combat(mgr: RunManager) -> dict:
    """直接判胜当前战斗（走 _end_combat 触发胜场钩子）并结算奖励链。"""
    combat = mgr.get_combat_state()
    assert combat is not None and not combat.is_over
    combat._end_combat(player_won=True)
    return mgr._resolve_combat_end()


def _drive_phase(mgr: RunManager) -> None:
    """把非地图/战斗阶段推进到 MAP_CHOICE / BOSS_RELIC / RUN_OVER。"""
    for _ in range(_MAX_DRIVER_STEPS):
        if mgr.phase in (RunManager.PHASE_MAP_CHOICE, RunManager.PHASE_BOSS_RELIC):
            return
        if mgr.phase == RunManager.PHASE_COMBAT:
            if mgr.get_combat_state().is_over:
                mgr._resolve_combat_end()
            else:
                _win_combat(mgr)
            continue
        if mgr.phase == RunManager.PHASE_CARD_REWARD:
            mgr.take_action({"action": "skip"})
            continue
        if mgr.phase == RunManager.PHASE_SHOP:
            mgr.take_action({"action": "leave_shop"})
            continue
        if mgr.phase == RunManager.PHASE_REST_SITE:
            opt = next(o for o in mgr._rest_options if o.enabled)
            mgr.take_action({"action": "rest_option", "option_id": opt.option_id})
            continue
        if mgr.phase == RunManager.PHASE_EVENT:
            opts = mgr.get_available_actions()
            if opts:
                first = opts[0]
                act = {"action": first["action"]}
                if "option_id" in first:
                    act["option_id"] = first["option_id"]
                if "index" in first:
                    act["index"] = first["index"]
                mgr.take_action(act)
            else:
                mgr.take_action({"action": "event_choice", "option_id": "leave"})
            continue
        if mgr.phase == RunManager.PHASE_TREASURE:
            mgr.take_action({"action": "collect"})
            continue
        return
    raise AssertionError("driver exceeded step bound")


def _walk_to_boss_and_win(mgr: RunManager) -> None:
    """在当前幕从地图入口一路走到 boss 节点并取胜（进阶无关的通用走图）。"""
    for _ in range(_MAX_DRIVER_STEPS):
        _drive_phase(mgr)
        assert mgr.phase == RunManager.PHASE_MAP_CHOICE, mgr.phase
        moves = [a for a in mgr.get_available_actions() if a["action"] == "move"]
        assert moves, "no reachable map point"
        target = max(moves, key=lambda a: a["coord"][1])
        mgr.take_action({"action": "move", "coord": target["coord"]})
        if mgr.phase == RunManager.PHASE_COMBAT:
            room_type = mgr._current_room_type
            _win_combat(mgr)
            _drive_phase(mgr)
            if room_type == RoomType.BOSS:
                return
            continue
        if mgr.is_over:
            return
    raise AssertionError("walk to boss exceeded step bound")


def _jump_to_final_act(mgr: RunManager) -> None:
    while mgr.run_state.current_act_index < len(mgr.run_state.acts) - 1:
        mgr._transition_next_act()


# ---------------------------------------------------------------------------
# RNG 具名流接线
# ---------------------------------------------------------------------------

class TestF3Point1NamedStreamWiring:
    def test_runrngset_named_streams_and_seed_formula_match_csharp(self):
        """锁:12 条具名流存在 + 流名种子派生公式逐位对齐 C#。

        C# RunRngSet.cs:157-161 CreateRng = new Rng(Seed, SnakeCase(类型名));
        Rng.cs:59-62 Rng(ulong, string) = seed + (uint)GetDeterministicHashCode(name)。
        """
        master_seed = 777
        rng_set = RunRngSet(master_seed)
        base = _uint32(deterministic_hash_code(str(master_seed)))
        expected = {
            "up_front": "up_front",
            "shuffle": "shuffle",
            "unknown_map_point": "unknown_map_point",
            "combat_card_generation": "combat_card_generation",
            "combat_potion_generation": "combat_potion_generation",
            "combat_card_selection": "combat_card_selection",
            "combat_energy_costs": "combat_energy_costs",
            "combat_targets": "combat_targets",
            "monster_ai": "monster_ai",
            "niche": "niche",
            "combat_orbs": "combat_orbs",
            "treasure_room": "treasure_room_relics",
        }
        for attr, snake_name in expected.items():
            stream = getattr(rng_set, attr)
            assert isinstance(stream, Rng)
            assert stream.seed == _uint32(base + _uint32(deterministic_hash_code(snake_name))), attr

    def test_run_manager_has_no_private_rng_stream(self):
        """锁:私有流 Rng(seed+9999) 与 RUN_MANAGER_RNG_SEED_OFFSET 已删除
        （C# RunManager 无任何私有 RNG 流,见 RunManager.cs 全文仅引用 State.Rng.*）。"""
        import sts2_env.run.run_manager as rm_module

        assert not hasattr(rm_module, "RUN_MANAGER_RNG_SEED_OFFSET")
        mgr = RunManager(seed=11, character_id="Ironclad")
        assert not hasattr(mgr, "_rng")
        assert not hasattr(mgr, "_heal_after_combat")  # 治疗常数路径一并清除

    def test_combat_entry_consumes_up_front_and_niche_not_private_stream(self):
        """锁:进战斗 = up_front 1 抽(encounter 选择) + niche 抽(setup 链);
        combat.rng 种子 = C# 公式派生(无坐标时 ActIndex+CombatId 回退分支)。"""
        mgr = RunManager(seed=23, character_id="Ironclad")
        up_before = mgr.run_state.rng.up_front.counter
        niche_before = mgr.run_state.rng.niche.counter
        mgr._enter_combat(RoomType.MONSTER)
        assert mgr.run_state.rng.up_front.counter == up_before + 1
        assert mgr.run_state.rng.niche.counter > niche_before
        # 公式:RunState.cs:64-74 CurrentMapCoord=最后访问坐标,未访问为 null
        # → C# CombatState.cs:136 回退分支 ActIndex + CombatId(combat_id 占位 0)
        expected_seed = _uint32(0 + 0)  # current_act_index(0) + combat_id(0)
        assert mgr._combat.rng.seed == expected_seed
        # 有坐标时走 Seed+col 分支(CombatState.cs:136 主分支)
        mgr.run_state.add_visited_coord(MapCoord(2, 3))
        mgr._enter_combat(RoomType.MONSTER)
        expected_seed2 = _uint32(int(_uint32(deterministic_hash_code("23"))) + 2)
        assert mgr._combat.rng.seed == expected_seed2

    def test_same_seed_same_board_encounter_and_combat_seed_deterministic(self):
        """锁:同 seed 同局面 → encounter 身份/combat rng 种子/流计数逐位一致;
        不同 seed → encounter 可分辨(非恒定)。"""
        def probe(seed: int):
            mgr = RunManager(seed=seed, character_id="Ironclad")
            counters = (
                mgr.run_state.rng.up_front.counter,
                mgr.run_state.rng.niche.counter,
            )
            mgr._enter_combat(RoomType.MONSTER)
            combat = mgr._combat
            return {
                "counters": counters,
                "up_after": mgr.run_state.rng.up_front.counter,
                "niche_after": mgr.run_state.rng.niche.counter,
                "combat_seed": combat.rng.seed,
                "enemy_ids": tuple(getattr(e, "monster_id", "") for e in combat.enemies),
                "enemy_hps": tuple(e.max_hp for e in combat.enemies),
            }

        a, b = probe(4242), probe(4242)
        assert a == b
        c = probe(4243)
        assert a["combat_seed"] != c["combat_seed"] or a["enemy_ids"] != c["enemy_ids"]


# ---------------------------------------------------------------------------
# boss 遗物池对账 + 宝箱遗物流
# ---------------------------------------------------------------------------

class TestF4BossRelicPoolAndTreasureStream:
    def test_boss_pool_entries_are_csharp_ancient_rarity_relics(self):
        """锁:池内 11 项全部是已移植遗物且 Python registry 稀有度 = ANCIENT,
        与 C# 一致(Astrolabe.cs:14 等 11 个文件均 RelicRarity.Ancient;
        Entities.Relics/RelicRarity.cs 枚举无 Boss 值)。池对账结论见
        run_manager._BOSS_RELIC_POOL 上方注释: C# 无 boss 三选一流程,
        本池为 Python 训练环境自有构造,不伪照 C# 改写。"""
        load_all_relics()
        assert len(_BOSS_RELIC_POOL) == 11
        for relic_name in _BOSS_RELIC_POOL:
            relic_id = RelicId[relic_name]
            assert RELIC_REGISTRY[relic_id].rarity == RelicRarity.ANCIENT, relic_name

    def test_boss_relic_offer_draws_treasure_room_named_stream(self):
        """锁:抽取消费 run 级 TreasureRoomRelics 流(流名
        treasure_room_relics,RunRngSet.cs:93 + RunRngType.cs:16),
        不再消费任何私有流。"""
        mgr = RunManager(seed=31, character_id="Ironclad")
        before = mgr.run_state.rng.treasure_room.counter
        mgr._enter_boss_relic()
        assert mgr.run_state.rng.treasure_room.counter > before
        # Fisher-Yates shuffle 抽取数 = len(candidates) - 1(core/rng.py shuffle)
        assert mgr._boss_relics  # 11 项全未持有 → 必然给满 3 个
        assert len(mgr._boss_relics) == 3

    def test_boss_relic_offer_deterministic_same_seed(self):
        """锁:同 seed 同局面(同持有集) → 三选一结果逐位一致。"""
        def offer(seed: int, owned: tuple[str, ...]):
            mgr = RunManager(seed=seed, character_id="Ironclad")
            for rid in owned:
                mgr.run_state.player.relics.append(rid)
            mgr._enter_boss_relic()
            return tuple(mgr._boss_relics)

        assert offer(97, ()) == offer(97, ())
        assert offer(97, ()) != offer(98, ())  # 不同 seed 结果可分辨

    def test_boss_relic_offer_excludes_owned(self):
        """锁:已持有剔除语义——持有者不出现;持有 8 项时候选恰为剩余 3 项。"""
        mgr = RunManager(seed=5, character_id="Ironclad")
        owned = _BOSS_RELIC_POOL[:8]
        for rid in owned:
            mgr.run_state.player.relics.append(rid)
        mgr._enter_boss_relic()
        assert set(mgr._boss_relics) == set(_BOSS_RELIC_POOL[8:])
        assert not (set(mgr._boss_relics) & set(owned))


# ---------------------------------------------------------------------------
# 战后治疗（遗物驱动）
# ---------------------------------------------------------------------------

def _won_combat_with_relics(relics: list[str], player_hp: int = 40) -> CombatState:
    combat = CombatState(
        player_hp=player_hp,
        player_max_hp=80,
        deck=create_ironclad_starter_deck(),
        rng_seed=7,
        relics=relics,
        character_id="Ironclad",
    )
    creature, ai = create_shrinker_beetle(Rng(7))
    combat.add_enemy(creature, ai)
    combat.start_combat()
    combat._end_combat(player_won=True)  # 触发 after_combat_end + after_combat_victory
    return combat


class TestF9RelicDrivenHeal:
    def test_victory_heal_is_relic_driven_once_not_config_doubled(self):
        """锁:持 BURNING_BLOOD 胜场恰 +6(遗物钩子,combat 内结算);
        修复前 = 遗物 +6 与 config 常数 +6 叠加成 +12。
        C# BurningBlood.cs:14 HealVar(6m) / :16-23 AfterCombatVictory,
        经 CombatManager.cs:1329 Hook.AfterCombatVictory 单次触发。"""
        mgr = RunManager(seed=13, character_id="Ironclad")
        assert "BURNING_BLOOD" in mgr.run_state.relics
        combat = _won_combat_with_relics(["BURNING_BLOOD"], player_hp=40)
        assert combat.player.current_hp == 46  # 钩子在 combat 内已治疗
        mgr._combat = combat
        mgr._current_room_type = RoomType.MONSTER
        mgr.run_state.potion_reward_odds.current_value = -1.0
        mgr._resolve_combat_end()
        assert mgr.run_state.player.current_hp == 46  # 无第二次 +6

    def test_without_burning_blood_no_victory_heal(self):
        """锁:换掉 BURNING_BLOOD 后胜场不再 +6(C# 遗物驱动语义:
        监听者消失即无治疗;修复前 config 常数无持有校验照治)。"""
        mgr = RunManager(seed=14, character_id="Ironclad")
        mgr.run_state.relics.remove("BURNING_BLOOD")
        assert "BURNING_BLOOD" not in mgr.run_state.relics
        combat = _won_combat_with_relics(list(mgr.run_state.relics), player_hp=40)
        assert combat.player.current_hp == 40  # combat 内零治疗
        mgr._combat = combat
        mgr._current_room_type = RoomType.MONSTER
        mgr.run_state.potion_reward_odds.current_value = -1.0
        mgr._resolve_combat_end()
        assert mgr.run_state.player.current_hp == 40

    def test_black_blood_heals_12_matching_csharp(self):
        """锁:BLACK_BLOOD 语义 = +12(C# BlackBlood.cs:14 HealVar(12m),
        同 AfterCombatVictory 钩子)——换表 BURNING_BLOOD→BLACK_BLOOD
        (relics/shop_event.py)后按 C# 数值治疗。"""
        combat = _won_combat_with_relics(["BlackBlood"], player_hp=40)
        assert combat.player.current_hp == 52

    def test_config_constant_path_removed(self):
        """锁:heal_after_combat config 常数与 _heal_after_combat 死路径已删除;
        各角色配置不再携带该键;结果 dict "healed" 键保留(恒 0,兼容消费方)。"""
        for cfg in _CHARACTER_CONFIG.values():
            assert "heal_after_combat" not in cfg
        mgr = RunManager(seed=15, character_id="Ironclad")
        assert not hasattr(mgr, "_heal_after_combat")
        mgr._combat = _won_combat_with_relics(["BURNING_BLOOD"], player_hp=70)
        mgr._current_room_type = RoomType.MONSTER
        mgr.run_state.potion_reward_odds.current_value = -1.0
        info = mgr._resolve_combat_end()
        assert info["healed"] == 0
        assert mgr.run_state.player.current_hp == 76  # 70 + 6(遗物)


# ---------------------------------------------------------------------------
# DoubleBoss 进阶
# ---------------------------------------------------------------------------

class TestF6DoubleBossAscension:
    def test_asc0_map_has_no_second_boss_and_generation_is_rng_neutral(self):
        """锁(进阶 0 零变化):has_second_boss=False 时不消耗额外 RNG(计数器
        相同)→ 现有任何 seed 的地图轨迹逐位不变;second_boss_point 恒 None。"""
        rng_a = Rng(12345)
        rng_b = Rng(12345)
        map_a = generate_act_map(num_rooms=15, rng=rng_a, act_index=0)
        map_b = generate_act_map(num_rooms=15, rng=rng_b, act_index=0,
                                 has_second_boss=True)
        assert rng_a.counter == rng_b.counter  # 挂节点零 RNG 消耗
        assert map_a.second_boss_point is None
        # 同 RNG 计数下两图结构相同(挂节点只加 meta 节点,不改网格)
        pts_a = sorted((p.coord.col, p.coord.row, p.point_type.name)
                       for p in map_a.all_points())
        pts_b = sorted((p.coord.col, p.coord.row, p.point_type.name)
                       for p in map_b.all_points())
        assert pts_a == pts_b
        assert map_b.boss_point.children == [map_b.second_boss_point]
        # asc0 run 全幕无 second_boss_point
        rs = RunState(seed=7, ascension_level=0)
        rs.initialize_run()
        for idx in range(len(rs.acts)):
            rs.enter_act(idx)
            assert rs.map.second_boss_point is None
            assert not rs.has_double_boss

    def test_asc10_second_boss_point_on_final_act_only(self):
        """锁:进阶 10 仅最终幕挂第二 boss 节点(C# RunManager.cs:761
        i == State.Acts.Count - 1),位置 = boss 同列 +1 行
        (StandardActMap.cs:94-99),boss.children 连边(:226-228),
        point_type=BOSS(:303-305),get_point 可解析(ActMap.cs:76-79)。"""
        rs = RunState(seed=7, ascension_level=10)
        rs.initialize_run()
        assert rs.has_double_boss
        for idx in range(len(rs.acts) - 1):
            rs.enter_act(idx)
            assert rs.map.second_boss_point is None
        rs.enter_act(len(rs.acts) - 1)
        act_map = rs.map
        sbp = act_map.second_boss_point
        assert sbp is not None
        assert sbp.coord.col == act_map.boss_point.coord.col
        assert sbp.coord.row == act_map.boss_point.coord.row + 1
        assert act_map.boss_point.children == [sbp]
        assert sbp.point_type.name == "BOSS"
        assert act_map.get_point(sbp.coord) is sbp

    def test_asc10_first_boss_win_returns_to_map_second_boss_offered(self):
        """锁:最终幕第一场 boss 胜利后回 MAP_CHOICE 且唯一可达 = 第二 boss 节点
        (C# CombatManager.cs:1335-1337 须在 SecondBossMapPoint 取胜才记 WinTime;
        AutoSlayer.cs:219 第一场后继续导航),不进 BOSS_RELIC。"""
        mgr = RunManager(seed=77, character_id="Ironclad", ascension_level=10)
        _jump_to_final_act(mgr)
        _walk_to_boss_and_win(mgr)
        assert not mgr.run_state.is_over
        assert mgr.phase == RunManager.PHASE_MAP_CHOICE
        sbp = mgr.run_state.map.second_boss_point
        assert sbp.coord not in mgr.run_state.visited_map_coords
        available = mgr.run_state.get_available_next_coords()
        assert available == [sbp.coord]

    def test_asc10_second_boss_encounter_differs_from_first(self):
        """锁:第二场 boss encounter 排除第一场(C# RunManager.cs:763
        AllBossEncounters.Where(e => e.Id != act.BossEncounter.Id);
        RoomSet.cs:76-86 NextBossEncounter:bossEncountersVisited != 0 且
        SecondBoss 非空 → SecondBoss)。同 seed 下两场 boss 出怪构成可分辨。"""
        from sts2_env.run.run_manager import _get_encounter_pools

        mgr = RunManager(seed=77, character_id="Ironclad", ascension_level=10)
        rs = mgr.run_state
        _jump_to_final_act(mgr)
        act_map = rs.map
        # 直落 boss 点(等价于走图到达):第一场从 up_front 全量 boss 池选择
        rs.add_visited_coord(act_map.boss_point.coord, room_type=RoomType.BOSS)
        mgr._enter_combat(RoomType.BOSS)
        first_setup = mgr._current_boss_setup
        assert first_setup is not None
        assert first_setup in _get_encounter_pools(2)["boss"]
        first_enemies = tuple(e.max_hp for e in mgr._combat.enemies)

        # 第二场:up_front 选择被限制在排除 first_setup 后的池
        pool_excl = [fn for fn in _get_encounter_pools(2)["boss"]
                     if fn is not first_setup]
        assert len(pool_excl) == len(_get_encounter_pools(2)["boss"]) - 1
        rs.add_visited_coord(act_map.second_boss_point.coord, room_type=RoomType.BOSS)
        mgr._enter_combat(RoomType.BOSS)
        assert mgr._current_boss_setup is first_setup  # 第一场记录未被覆盖
        second_enemies = tuple(e.max_hp for e in mgr._combat.enemies)
        assert second_enemies != first_enemies

    def test_asc10_run_won_only_after_both_bosses(self):
        """锁:双胜才判胜——第一场胜后 run 未结束;第二场胜 → boss 遗物 →
        换幕 → is_over && player_won(C# WinTime 判定 CombatManager.cs:1335-1338)。"""
        mgr = RunManager(seed=77, character_id="Ironclad", ascension_level=10)
        _jump_to_final_act(mgr)
        _walk_to_boss_and_win(mgr)
        assert not mgr.run_state.is_over and not mgr.run_state.player_won
        sbp = mgr.run_state.map.second_boss_point
        mgr.take_action({"action": "move", "coord": (sbp.coord.col, sbp.coord.row)})
        assert mgr.phase == RunManager.PHASE_COMBAT
        _win_combat(mgr)
        _drive_phase(mgr)
        assert mgr.phase == RunManager.PHASE_BOSS_RELIC
        assert len(mgr._boss_relics) == 3
        mgr.take_action({"action": "pick_relic", "index": 0})
        _drive_phase(mgr)
        assert mgr.run_state.is_over
        assert mgr.run_state.player_won

    def test_asc0_final_boss_flow_unchanged(self):
        """锁(进阶 0 行为零变化):最终幕 boss 胜利后直接进 BOSS_RELIC
        (无双 boss 门控分叉),后续换幕判胜同旧路径。"""
        mgr = RunManager(seed=77, character_id="Ironclad", ascension_level=0)
        assert not mgr.run_state.has_double_boss
        _jump_to_final_act(mgr)
        _walk_to_boss_and_win(mgr)
        assert mgr.run_state.map.second_boss_point is None
        assert mgr.phase == RunManager.PHASE_BOSS_RELIC
        assert len(mgr._boss_relics) == 3
        mgr.take_action({"action": "pick_relic", "index": 0})
        _drive_phase(mgr)
        assert mgr.run_state.is_over
        assert mgr.run_state.player_won
