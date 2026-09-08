"""遭遇选择弱/强怪池分层单测(09-05 用户评审修复)。

真实规则(sts2_env/run/run_manager.py:549-558):
BOSS→boss 池、ELITE→elite 池、MONSTER 房按 act_floor ≤ num_weak_encounters
分 weak/normal 池。此前 pick_encounter 所有 MONSTER 房一律 normal 池,第一幕
前 3 层(弱怪位)构筑被喂强怪,weak 池从未被使用。

断言方式:pick_encounter 返回 setup 函数对象,用「函数对象 in 池列表」身份
断言池来源(weak/normal 池间可能有同名怪但 setup 函数互异,先做不相交前置
检查保证身份断言有效);再补蒙特卡洛多次抽样验证随机覆盖非单点。
"""

from __future__ import annotations

import random

import pytest

# ---------------------------------------------------------------------------
# 以下三个符号原样内联自训练侧的 loadout 模块(NUM_WEAK_ENCOUNTERS /
# is_weak_floor / pick_encounter,函数体逐字节一致),使本测试不依赖该模块。
# 语义:按快照 act+room_type+幕内楼层从与
# run_manager 同源的遭遇池随机选 setup。
# ---------------------------------------------------------------------------
NUM_WEAK_ENCOUNTERS = {0: 3, 1: 2, 2: 2, 3: 3}


def is_weak_floor(act_index: int, act_floor: int) -> bool:
    """幕内弱怪位判定(单源实现):act_floor ≤ 该幕弱怪楼层数 → weak 位。

    阈值/比较规则禁在调用侧复写(防两处漂移):采集端 pick_encounter 分池
    与评估端分层共用本函数。
    默认 3 = 未知幕兜底,与 run_manager._enter_combat 同规则。
    """
    return int(act_floor) <= NUM_WEAK_ENCOUNTERS.get(int(act_index), 3)


def pick_encounter(snapshot: dict, rng: random.Random):
    """按快照 act+room_type+幕内楼层从同款遭遇池随机选 setup(_get_encounter_pools
    与 run_manager 同源;分池规则复刻 run_manager._enter_combat:BOSS→boss、
    ELITE→elite、MONSTER/UNKNOWN 按 act_floor ≤ NUM_WEAK_ENCOUNTERS[act]
    分 weak/normal——构筑-遭遇分布对齐到同类节点+幕内弱强位粒度)。

    fail-loud:快照缺 act_floor 键直接 raise(旧库无该字段,分池协议需
    新采集),禁止静默回落 normal 池把弱怪位喂成强怪。
    """
    from sts2_env.run.run_manager import _get_encounter_pools

    act = int(snapshot.get("act_index", 0))
    room_type = str(snapshot.get("room_type", ""))
    if room_type == "BOSS":
        pool_key = "boss"
    elif room_type == "ELITE":
        pool_key = "elite"
    else:
        try:
            act_floor = int(snapshot["act_floor"])
        except KeyError as e:
            raise KeyError(
                f"snapshot {snapshot.get('uid', '?')} 缺 act_floor:"
                "旧库无 act_floor,分池协议需新采集") from e
        pool_key = "weak" if is_weak_floor(act, act_floor) else "normal"
    pools = _get_encounter_pools(act)
    cands = pools.get(pool_key) or pools["normal"]
    return rng.choice(list(cands))


def _snap(act: int = 0, act_floor: int = 1, room: str = "MONSTER") -> dict:
    return dict(
        uid=f"e-{act}-{act_floor}-{room}#0", ep_uid="e", arm="probe", seed=1,
        combat_idx=0, act_index=act, floor=10, act_floor=act_floor,
        room_type=room, hp=55, max_hp=75, gold=99,
        deck=[["STRIKE_DEFECT", False]],
        relics=[], potions=[], monsters=["X"],
    )


def _pools(act: int):
    """与 _get_encounter_pools(act) 对应的上游池模块(直接 import 断身份)。"""
    from sts2_env.run.run_manager import _get_encounter_pools

    modules = {0: "act1", 1: "act2", 2: "act3", 3: "act4"}
    mod = __import__(f"sts2_env.encounters.{modules[act]}",
                     fromlist=("WEAK_ENCOUNTERS",))
    pools = _get_encounter_pools(act)
    # 前置:identity 断言有效的前提——_get_encounter_pools 返回的确实是
    # 上游池模块的同一批函数对象,且 weak/normal 池按函数对象不相交
    assert set(pools["weak"]) == set(mod.WEAK_ENCOUNTERS)
    assert set(pools["boss"]) == set(mod.BOSS_ENCOUNTERS)
    assert not (set(mod.WEAK_ENCOUNTERS) & set(mod.NORMAL_ENCOUNTERS)), \
        "weak/normal 池存在同名 setup,身份断言失效"
    return mod


def test_num_weak_encounters_matches_c_number_of_weak_encounters():
    """每幕弱怪楼层数 = C# NumberOfWeakEncounters(acts.py 同款:0/3 幕 3,1/2 幕 2)。"""
    assert NUM_WEAK_ENCOUNTERS == {0: 3, 1: 2, 2: 2, 3: 3}


@pytest.mark.parametrize("act_floor", [1, 2, 3])
def test_act0_weak_floors_draw_from_weak_pool(act_floor):
    """第一幕 act_floor=1/2/3(弱怪位)→ act1.py WEAK_ENCOUNTERS 抽取。"""
    mod = _pools(0)
    rng = random.Random(act_floor)
    setups = {pick_encounter(_snap(0, act_floor), rng) for _ in range(40)}
    assert setups and all(s in mod.WEAK_ENCOUNTERS for s in setups)


@pytest.mark.parametrize("act_floor", [4, 5, 12])
def test_act0_normal_floors_draw_from_normal_pool(act_floor):
    """第一幕 act_floor=4+(超阈值)→ act1.py NORMAL_ENCOUNTERS 抽取。"""
    mod = _pools(0)
    rng = random.Random(act_floor)
    setups = {pick_encounter(_snap(0, act_floor), rng) for _ in range(40)}
    assert setups and all(s in mod.NORMAL_ENCOUNTERS for s in setups)
    assert not any(s in mod.WEAK_ENCOUNTERS for s in setups)


def test_act1_threshold_is_two():
    """第二幕阈值=2:act_floor=2 → weak、3 → normal(池来自 act2.py)。"""
    mod = _pools(1)
    rng = random.Random(11)
    weak = {pick_encounter(_snap(1, 2), rng) for _ in range(40)}
    normal = {pick_encounter(_snap(1, 3), rng) for _ in range(40)}
    assert weak and all(s in mod.WEAK_ENCOUNTERS for s in weak)
    assert normal and all(s in mod.NORMAL_ENCOUNTERS for s in normal)
    # 蒙特卡洛覆盖:两侧各抽到 >1 种 setup(池内随机,非单点)
    assert len(weak) > 1 and len(normal) > 1


def test_elite_boss_ignore_act_floor():
    """ELITE/BOSS 池不受 act_floor 影响(run_manager 分支先于弱强分层)。"""
    mod = _pools(0)
    rng = random.Random(7)
    for floor in (1, 99):                      # 弱怪位/超深楼层都不变
        elite = {pick_encounter(_snap(0, floor, "ELITE"), rng)
                 for _ in range(20)}
        boss = {pick_encounter(_snap(0, floor, "BOSS"), rng)
                for _ in range(20)}
        assert elite and all(s in mod.ELITE_ENCOUNTERS for s in elite)
        assert boss and all(s in mod.BOSS_ENCOUNTERS for s in boss)


def test_unknown_room_follows_weak_normal_layering():
    """UNKNOWN(事件怪)沿用 MONSTER 同款 act_floor 分层(旧口径走 normal 的修订)。"""
    mod = _pools(0)
    rng = random.Random(13)
    weak = {pick_encounter(_snap(0, 1, "UNKNOWN"), rng) for _ in range(30)}
    normal = {pick_encounter(_snap(0, 5, "UNKNOWN"), rng) for _ in range(30)}
    assert weak and all(s in mod.WEAK_ENCOUNTERS for s in weak)
    assert normal and all(s in mod.NORMAL_ENCOUNTERS for s in normal)


def test_missing_act_floor_raises_loud():
    """快照缺 act_floor 键 → KeyError 带提示(旧库须新采集,禁静默回落 normal)。"""
    snap = _snap(0, 1)
    del snap["act_floor"]
    with pytest.raises(KeyError, match="act_floor.*新采集"):
        pick_encounter(snap, random.Random(0))
