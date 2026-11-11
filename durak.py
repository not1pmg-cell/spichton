"""Durak (36 karta, 2 o'yinchi): podkidnoy va perevodnoy. Server — hakam, kartalar yashirin."""
import random

def suit(c): return c // 9
def rank(c): return 6 + c % 9

class Durak:
    def __init__(s, transfer=False):
        s.tr = transfer
        s.deck = list(range(36)); random.shuffle(s.deck)
        s.hand = [[], []]
        for _ in range(6):
            for p in (0, 1): s.hand[p].append(s.deck.pop())
        s.trump = suit(s.deck[0])                      # pastdagi karta — kozir
        lows = [(rank(c), p) for p in (0, 1) for c in s.hand[p] if suit(c) == s.trump]
        s.att = min(lows)[1] if lows else 0
        s.disc = 0; s.winner = None
        s._bout()

    # --- yordamchilar
    @property
    def dfn(s): return 1 - s.att
    def _bout(s):
        s.table = []; s.taking = False
        s.dcap = min(6, len(s.hand[s.dfn]))
    def undef(s): return [i for i, p in enumerate(s.table) if p[1] is None]
    def beats(s, a, d):
        return (suit(a) == suit(d) and rank(d) > rank(a)) or (suit(d) == s.trump and suit(a) != s.trump)
    def can_add(s, c):
        if len(s.table) >= s.dcap: return False
        return not s.table or rank(c) in {rank(x) for p in s.table for x in p if x is not None}
    def waiting(s):
        if s.winner is not None: return None
        if s.taking: return s.att
        return s.dfn if s.undef() else s.att
    def _k(s, c): return (suit(c) == s.trump, rank(c))

    def _end(s):
        if not s.deck:
            e0, e1 = not s.hand[0], not s.hand[1]
            if e0 or e1: s.winner = -1 if e0 and e1 else (0 if e0 else 1)
    def _refill(s):
        for p in (s.att, 1 - s.att):
            while len(s.hand[p]) < 6 and s.deck: s.hand[p].append(s.deck.pop())
    def _finish(s):
        cards = [x for p in s.table for x in p if x is not None]; s.table = []
        if s.taking:
            s.hand[s.dfn] += cards; s._refill()
        else:
            s.disc += len(cards); s._refill(); s.att = 1 - s.att
        s._end()
        if s.winner is None: s._bout()
    def _auto(s):
        if s.winner is None and s.waiting() == s.att and s.table and (s.taking or not s.undef()):
            if not any(s.can_add(c) for c in s.hand[s.att]): s._finish()

    # --- harakatlar: att / def / tr / take / done
    def act(s, who, a, c=None, i=None):
        if s.winner is not None or who not in (0, 1): return False
        h = s.hand[who]
        if a == "att":
            if who != s.att or c not in h or not s.can_add(c): return False
            h.remove(c); s.table.append([c, None])
        elif a == "def":
            if who != s.dfn or s.taking or c not in h or i not in s.undef() or not s.beats(s.table[i][0], c): return False
            h.remove(c); s.table[i][1] = c
        elif a == "tr":
            if not s.tr or who != s.dfn or s.taking or c not in h or not s.table or any(p[1] is not None for p in s.table): return False
            if rank(c) != rank(s.table[0][0]) or len(s.table) + 1 > len(s.hand[s.att]): return False
            h.remove(c); s.table.append([c, None]); s.att = 1 - s.att; s.dcap = min(6, len(s.hand[s.dfn]))
        elif a == "take":
            if who != s.dfn or s.taking or not s.undef(): return False
            s.taking = True
        elif a == "done":
            if who != s.att or not s.table or (not s.taking and s.undef()): return False
            s._finish(); return True
        else: return False
        s._auto(); return True

    def view(s, i):
        h = sorted(s.hand[i], key=lambda c: (suit(c) == s.trump, suit(c), rank(c)))
        return {"h": h, "o": len(s.hand[1 - i]), "dk": len(s.deck), "tc": s.deck[0] if s.deck else None, "ts": s.trump,
                "tb": s.table, "at": s.att, "tk": s.taking, "w": s.waiting(), "ds": s.disc, "cap": s.dcap,
                "tr": int(s.tr), "win": s.winner}

    # --- avtomatik harakatlar (taymer va bot)
    def auto(s, w):
        if w == s.dfn and not s.taking: return ("take",)
        if not s.table: return ("att", min(s.hand[w], key=s._k))
        return ("done",)
    def bot(s, w):
        h = s.hand[w]
        if w == s.att:
            if not s.table: return ("att", min(h, key=s._k))
            adds = [c for c in h if s.can_add(c) and (suit(c) != s.trump or not s.deck)]
            if adds and (s.taking or random.random() < .7): return ("att", min(adds, key=s._k))
            return ("done",)
        if s.tr and not s.taking and all(p[1] is None for p in s.table):
            ts = [c for c in h if rank(c) == rank(s.table[0][0]) and suit(c) != s.trump and len(s.table) + 1 <= len(s.hand[s.att])]
            if ts and random.random() < .7: return ("tr", min(ts, key=s._k))
        plan = []
        for i in s.undef():
            cs = [c for c in h if c not in [p for p, _ in plan] and s.beats(s.table[i][0], c)]
            if not cs: return ("take",)
            c = min(cs, key=s._k)
            if suit(c) == s.trump and rank(c) < 11 and len(s.deck) > 3 and suit(s.table[i][0]) != s.trump: return ("take",)
            plan.append((c, i))
        return ("def", plan[0][0], plan[0][1])
