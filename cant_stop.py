#!/usr/bin/env python3
"""Can't Stop — 掷骰爬塔游戏（简化还原）。

规则：
- 4 颗骰子，每轮掷出后分成两对（和为 2..12），在对应列上放置/推进标记。
- 每人同时最多 3 个进行中的标记（runner）；爆掉（无法放置任一对）则本轮进度作废。
- 主动停手则把标记进度存档（bank）；一轮内完成的列会释放 runner 槽位。
- 列高度：2:3, 3:5, 4:7, 5:9, 6:11, 7:13, 8:11, 9:9, 10:7, 11:5, 12:3。
- 先完成 3 列者获胜。

纯标准库：argparse / random / sys / copy。
"""

import argparse
import copy
import random
import sys

# 列 -> 需要爬的格数（标准 Can't Stop）
COLUMN_HEIGHT = {2: 3, 3: 5, 4: 7, 5: 9, 6: 11, 7: 13,
                 8: 11, 9: 9, 10: 7, 11: 5, 12: 3}
COLUMNS = list(range(2, 13))
MAX_RUNNERS = 3
WIN_COLUMNS = 3


class IllegalMove(Exception):
    """非法走法。"""


def pair_options(dice):
    """4 颗骰子分成两对的全部组合（去重），返回 [(sum1, sum2), ...]。

    3 种分法：(0,1)(2,3)、(0,2)(1,3)、(0,3)(1,2)。
    """
    d = list(dice)
    if len(d) != 4:
        raise IllegalMove("必须恰好 4 颗骰子")
    splits = [((d[0], d[1]), (d[2], d[3])),
              ((d[0], d[2]), (d[1], d[3])),
              ((d[0], d[3]), (d[1], d[2]))]
    seen = set()
    out = []
    for (a, b), (c, e) in splits:
        key = tuple(sorted((a + b, c + e)))
        if key not in seen:
            seen.add(key)
            out.append((a + b, c + e))
    return out


class PlayerState:
    """一名玩家的永久进度：progress 列->已爬格数，completed 已完成列集合。"""

    def __init__(self):
        self.progress = {c: 0 for c in COLUMNS}
        self.completed = set()

    def clone(self):
        return copy.deepcopy(self)


class TurnState:
    """一轮内的临时进度：runners 列->本轮推进到的格数（共享 player 引用）。"""

    def __init__(self, player):
        self.player = player
        self.runners = {}
        self.done_this_turn = set()

    def _clone(self):
        t = copy.copy(self)
        t.runners = dict(self.runners)
        t.done_this_turn = set(self.done_this_turn)
        return t  # player 引用共享，不深拷贝

    def height(self, col):
        return self.runners.get(col, self.player.progress[col])

    def placeable(self, s):
        """和数 s 是否可放置（列未完成、有 runner 可推进或有空 runner 槽）。"""
        if s in self.player.completed or s in self.done_this_turn:
            return False
        if s in self.runners:
            return self.height(s) < COLUMN_HEIGHT[s]
        return len(self.runners) < MAX_RUNNERS

    def place_one(self, s):
        if not self.placeable(s):
            raise IllegalMove(f"列 {s} 不可放置")
        self.runners[s] = self.height(s) + 1
        if self.runners[s] >= COLUMN_HEIGHT[s]:
            # 本轮完成该列：释放 runner 槽位
            self.done_this_turn.add(s)
            del self.runners[s]
        return s

    def try_pair(self, s1, s2):
        """试放一对和数，返回 (放置数, 新 TurnState)；枚举两种顺序取优。"""
        best = None
        for order in ((s1, s2), (s2, s1)):
            t = self._clone()
            n = 0
            for s in order:
                if t.placeable(s):
                    t.place_one(s)
                    n += 1
            if best is None or n > best[0]:
                best = (n, t)
        return best

    def can_place(self, dice):
        for s1, s2 in pair_options(dice):
            n, _ = self.try_pair(s1, s2)
            if n > 0:
                return True
        return False

    def apply_best(self, dice):
        """按最优分对/顺序放置，返回新 TurnState；无处可放抛 IllegalMove。"""
        best = None
        for s1, s2 in pair_options(dice):
            n, t = self.try_pair(s1, s2)
            if best is None or n > best[0]:
                best = (n, t)
        if best is None or best[0] == 0:
            raise IllegalMove("无法放置这一掷")
        return best[1]

    def bank(self):
        """停手：把本轮进度存档进 player。"""
        for col in self.done_this_turn:
            self.player.completed.add(col)
            self.player.progress[col] = COLUMN_HEIGHT[col]
        for col, h in self.runners.items():
            self.player.progress[col] = h
            if h >= COLUMN_HEIGHT[col]:
                self.player.completed.add(col)
        self.runners = {}
        self.done_this_turn = set()


class CantStop:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.players = [PlayerState(), PlayerState()]

    def roll(self):
        return tuple(self.rng.randint(1, 6) for _ in range(4))

    def play_turn_auto(self, player_idx, ai_stop, verbose=False):
        """AI 自动走完一轮。返回 'bank' / 'bust'。"""
        p = self.players[player_idx]
        t = TurnState(p)
        while True:
            dice = self.roll()
            if verbose:
                print(f"  掷出 {dice} -> 可分对 {pair_options(dice)}")
            if not t.can_place(dice):
                if verbose:
                    print("  爆掉！本轮进度作废")
                return "bust"
            t = t.apply_best(dice)
            if verbose:
                print(f"  放置后 runner={t.runners} 本轮完成={sorted(t.done_this_turn)}")
            if ai_stop(t):
                t.bank()
                if verbose:
                    print(f"  停手存档：完成列 {sorted(p.completed)}")
                return "bank"

    def play_game(self, ai_stops, verbose=False, max_rounds=5000):
        """ai_stops: [p0_stop_fn, p1_stop_fn]。返回胜者 0/1。"""
        for _ in range(max_rounds):
            for i in (0, 1):
                self.play_turn_auto(i, ai_stops[i], verbose=verbose)
                if len(self.players[i].completed) >= WIN_COLUMNS:
                    return i
        c0, c1 = (len(self.players[0].completed), len(self.players[1].completed))
        return 0 if c0 >= c1 else 1


# ---------------- AI ----------------

def _gain(t):
    return sum(h - t.player.progress[c] for c, h in t.runners.items())


def greedy_stop(t):
    """贪心停手：接近完成、或 runner 满且推进足够、或总推进很大时停手。"""
    if not t.runners and not t.done_this_turn:
        return False
    if t.done_this_turn:
        return True
    if any(COLUMN_HEIGHT[c] - h <= 2 for c, h in t.runners.items()):
        return True
    if len(t.runners) >= MAX_RUNNERS and _gain(t) >= 4:
        return True
    return _gain(t) >= 8


def cautious_stop(t):
    """保守策略：稍有进展就停手。"""
    if not t.runners and not t.done_this_turn:
        return False
    if t.done_this_turn:
        return True
    if any(COLUMN_HEIGHT[c] - h <= 3 for c, h in t.runners.items()):
        return True
    return _gain(t) >= 3


# ---------------- 文本棋盘 ----------------

def render(players):
    lines = []
    lines.append("列: " + " ".join(f"{c:>2}" for c in COLUMNS))
    lines.append("高: " + " ".join(f"{COLUMN_HEIGHT[c]:>2}" for c in COLUMNS))
    for i, p in enumerate(players):
        row = " ".join(f"{p.progress[c]:>2}" for c in COLUMNS)
        done = ",".join(str(c) for c in sorted(p.completed))
        lines.append(f"P{i} : {row}  完成[{done or '-'}]")
    return "\n".join(lines)


# ---------------- CLI ----------------

def cmd_auto(args):
    wins = [0, 0]
    for g in range(args.games):
        game = CantStop(seed=args.seed + g if args.seed is not None else None)
        w = game.play_game([greedy_stop, cautious_stop], verbose=args.verbose)
        wins[w] += 1
        if args.verbose:
            print(f"--- 第 {g + 1} 局：玩家{w} 胜 ---")
            print(render(game.players))
    print(f"共 {args.games} 局：玩家0(贪心)胜 {wins[0]}，玩家1(保守)胜 {wins[1]}")


def cmd_play(args):
    game = CantStop(seed=args.seed)
    print("Can't Stop 人机对战：你是玩家0，AI 是玩家1。")
    print("每轮掷骰后程序自动用最优分对放置，你只决定继续(c)/停手(s)/退出(q)。")
    while True:
        p = game.players[0]
        t = TurnState(p)
        print(render(game.players))
        while True:
            dice = game.roll()
            print(f"掷出 {dice} -> {pair_options(dice)}")
            if not t.can_place(dice):
                print("爆掉！本轮进度作废。")
                break
            t = t.apply_best(dice)
            print(f"放置后 runner={t.runners} 本轮完成={sorted(t.done_this_turn)}")
            cmd = input("继续(c)/停手存档(s)/退出(q)：").strip().lower()
            if cmd == "q":
                return
            if cmd == "s":
                t.bank()
                print(f"存档完成，已完成列 {sorted(p.completed)}")
                break
        if len(p.completed) >= WIN_COLUMNS:
            print("你赢了！")
            return
        res = game.play_turn_auto(1, greedy_stop)
        ai = game.players[1]
        print(f"AI 回合结束（{res}），AI 完成列 {sorted(ai.completed)}")
        if len(ai.completed) >= WIN_COLUMNS:
            print("AI 赢了。")
            return


def main(argv=None):
    ap = argparse.ArgumentParser(description="Can't Stop 掷骰爬塔游戏")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auto", help="AI 自动对战演示")
    a.add_argument("--games", type=int, default=10)
    a.add_argument("--verbose", action="store_true")
    a.add_argument("--seed", type=int, default=None)
    pl = sub.add_parser("play", help="人机对战")
    pl.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    if args.cmd == "auto":
        cmd_auto(args)
    elif args.cmd == "play":
        if not sys.stdin.isatty():
            print("交互模式需要终端。", file=sys.stderr)
            return 2
        cmd_play(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
