"""Générateur déterministe d'items de fractions (qualité premium).

Math EXACTE via `fractions.Fraction` : la réponse est calculée, jamais devinée.
Distracteurs fondés sur les ERREURS CLASSIQUES d'élèves (ajouter les dénominateurs,
oublier de simplifier, inverser numérateur/dénominateur, etc.) — un bon distracteur
diagnostique une méprise précise.

Un générateur par code de compétence (registre `GENERATORS`). Chaque générateur
renvoie une liste de dicts {stem, options, answer} valides `ItemContent` (MCQ).
Les items « visuels » sont rendus vérifiables par description verbale du modèle.
"""
from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Callable, Dict, List

GENERATORS: Dict[str, Callable[[], List[dict]]] = {}


def _register(code: str):
    def deco(fn):
        GENERATORS[code] = fn
        return fn
    return deco


# --- helpers d'affichage ---

def fs(fr: Fraction) -> str:
    """Affiche une fraction sous forme n/d (sans réduire l'affichage)."""
    return f"{fr.numerator}/{fr.denominator}"

def raw(n: int, d: int) -> str:
    return f"{n}/{d}"

def mixed(fr: Fraction) -> str:
    """Affiche en nombre mixte si > 1, sinon fraction simple / entier."""
    if fr.denominator == 1:
        return str(fr.numerator)
    w = fr.numerator // fr.denominator
    r = fr.numerator - w * fr.denominator
    if w and r:
        return f"{w} {r}/{fr.denominator}"
    if w:
        return str(w)
    return f"{r}/{fr.denominator}"


def _value(s: str):
    """Valeur numérique d'une option ('w n/d', 'n/d', entier), sinon None."""
    s = s.strip()
    m = re.fullmatch(r"(?:(\d+)\s+)?(\d+)/(\d+)", s)
    if m:
        if int(m.group(3)) == 0:
            return None
        return Fraction(int(m.group(1) or 0)) + Fraction(int(m.group(2)), int(m.group(3)))
    if re.fullmatch(r"-?\d+", s):
        return Fraction(int(s))
    return None


def _mcq(stem: str, correct: str, distractors: List[str], salt: int) -> dict:
    """Assemble un MCQ : réponse + distracteurs distincts (3 à 4 options), position variée.

    Rejette tout distracteur identique à la réponse PAR LA VALEUR (ex. 6/8 vs 3/4) :
    deux options de même valeur = MCQ mal formé. Pas de padding parasite.
    """
    cval = _value(correct)
    opts = [correct]
    for d in distractors:
        if d in opts:
            continue
        dv = _value(d)
        if cval is not None and dv is not None and dv == cval:
            continue  # même valeur que la réponse → distracteur invalide
        opts.append(d)
        if len(opts) == 4:
            break
    k = salt % len(opts)
    opts = opts[k:] + opts[:k]  # rotation déterministe (varie la position de la réponse)
    return {"stem": stem, "options": opts, "answer": correct}


def _take(items: List[dict], n: int) -> List[dict]:
    return items[:n] if n else items


# ===================== Nombres & faits =====================

@_register("MATH.G3.NS.MULT_FACTS")
def _mult_facts() -> List[dict]:
    out = []
    pairs = [(6, 7), (8, 7), (9, 6), (7, 7), (8, 8), (9, 9), (6, 8), (9, 7), (12, 6), (8, 9)]
    for i, (a, b) in enumerate(pairs):
        p = a * b
        out.append(_mcq(f"What is {a} × {b}?", str(p),
                        [str(p + a), str(p - b), str(p + 1), str((a + 1) * b)], i))
    return out


@_register("MATH.G4.NS.FACTORS")
def _factors() -> List[dict]:
    out = []
    data = [(12, 4, 5), (18, 6, 4), (24, 8, 7), (20, 5, 6), (15, 3, 4),
            (16, 8, 6), (30, 6, 4), (28, 7, 8), (36, 9, 8), (45, 9, 7)]
    for i, (n, fac, nonfac) in enumerate(data):
        out.append(_mcq(f"Which number is a factor of {n}?", str(fac),
                        [str(nonfac), str(n + 1), str(n - 1)], i))
    return out


@_register("MATH.G4.NS.LCM")
def _lcm() -> List[dict]:
    out = []
    pairs = [(4, 6), (3, 5), (6, 8), (4, 10), (6, 9), (8, 12), (5, 6), (9, 12), (4, 14), (10, 15)]
    for i, (a, b) in enumerate(pairs):
        l = math.lcm(a, b)
        out.append(_mcq(f"What is the least common multiple of {a} and {b}?", str(l),
                        [str(a * b), str(a + b), str(math.gcd(a, b))], i))
    return out


@_register("MATH.G4.NS.GCD")
def _gcd() -> List[dict]:
    out = []
    pairs = [(12, 18), (24, 36), (16, 24), (15, 20), (18, 27), (8, 12), (30, 45), (14, 21), (20, 50), (28, 42)]
    for i, (a, b) in enumerate(pairs):
        g = math.gcd(a, b)
        out.append(_mcq(f"What is the greatest common divisor of {a} and {b}?", str(g),
                        [str(math.lcm(a, b)), str(abs(a - b)), str(g * 2)], i))
    return out


# ===================== Concept de fraction =====================

@_register("MATH.G3.NF.UNIT_FRACTION")
def _unit_fraction() -> List[dict]:
    out = []
    for i, b in enumerate([2, 3, 4, 5, 6, 8, 10, 12]):
        out.append(_mcq(f"A whole is split into {b} equal parts. What fraction is ONE part?",
                        raw(1, b), [raw(b, 1), raw(2, b), raw(1, b - 1)], i))
    return out


@_register("MATH.G3.NF.FRACTION_AS_PART")
def _fraction_as_part() -> List[dict]:
    out = []
    data = [(3, 4), (2, 5), (5, 6), (3, 8), (2, 3), (7, 10), (4, 5), (5, 12), (3, 5), (1, 6)]
    for i, (a, b) in enumerate(data):
        out.append(_mcq(
            f"A whole is divided into {b} equal parts and {a} parts are taken. "
            "What fraction is taken?", raw(a, b),
            [raw(b, a), raw(a, b - a), raw(a + 1, b)], i))
    return out


@_register("MATH.G3.NF.FRACTION_OF_SET")
def _fraction_of_set() -> List[dict]:
    out = []
    data = [(20, 3, 4), (18, 2, 3), (24, 5, 6), (15, 2, 5), (12, 3, 4),
            (30, 4, 5), (16, 3, 8), (28, 3, 7), (36, 5, 6), (21, 2, 3)]
    for i, (N, a, b) in enumerate(data):
        ans = N * a // b  # b divise N par construction
        out.append(_mcq(
            f"A set has {N} objects. {a}/{b} of them are red. How many are red?",
            str(ans), [str(N * b // a), str(N // b), str(N - ans)], i))
    return out


@_register("MATH.G3.NF.WHOLE_AS_FRACTION")
def _whole_as_fraction() -> List[dict]:
    out = []
    for i, b in enumerate([2, 3, 4, 5, 6, 8, 7, 10, 9, 12]):
        out.append(_mcq(f"Express 1 whole as a fraction with denominator {b}.", raw(b, b),
                        [raw(b, 1), raw(1, b), raw(b - 1, b)], i))
    return out


@_register("MATH.G3.NF.NUMBER_LINE_PLACE")
def _number_line() -> List[dict]:
    out = []
    data = [(1, 4), (3, 4), (2, 5), (3, 8), (5, 6), (1, 3), (2, 3), (4, 5), (5, 8), (7, 10)]
    for i, (a, b) in enumerate(data):
        out.append(_mcq(
            f"A number line from 0 to 1 is split into {b} equal intervals. "
            f"What fraction is at the {a}{'st' if a==1 else 'th'} tick after 0?",
            raw(a, b), [raw(a, b + 1), raw(a - 1, b), raw(b, a)], i))
    return out


# ===================== Visuels (décrits verbalement) =====================

@_register("MATH.G2.NS.EQUAL_SHARES")
def _equal_shares() -> List[dict]:
    out = []
    shapes = ["circle", "rectangle", "square", "pizza"]
    for i, b in enumerate([2, 3, 4, 6, 8]):
        sh = shapes[i % len(shapes)]
        out.append(_mcq(f"A {sh} is cut into {b} equal parts. What fraction is ONE part?",
                        raw(1, b), [raw(b, 1), raw(2, b), raw(1, b + 1)], i))
    return out


@_register("MATH.G2.NS.HALVES_QUARTERS")
def _halves_quarters() -> List[dict]:
    out = [
        _mcq("Which fraction means one half?", "1/2", ["1/4", "2/1", "1/3"], 0),
        _mcq("Which fraction means one quarter?", "1/4", ["1/2", "4/1", "1/3"], 1),
        _mcq("Two quarters make which fraction?", "1/2", ["1/4", "2/2", "3/4"], 2),
        _mcq("How many quarters make one whole?", "4", ["2", "3", "1"], 3),
        _mcq("How many halves make one whole?", "2", ["4", "1", "3"], 0),
    ]
    return out


@_register("MATH.G2.NS.NAME_FRACTION_VISUAL")
def _name_fraction_visual() -> List[dict]:
    out = []
    data = [(3, 4), (1, 2), (2, 3), (3, 8), (5, 6), (1, 4), (2, 5), (4, 6), (3, 5), (5, 8)]
    for i, (a, b) in enumerate(data):
        out.append(_mcq(
            f"A bar is divided into {b} equal parts and {a} parts are shaded. "
            "What fraction is shaded?", raw(a, b),
            [raw(b - a, b), raw(b, a), raw(a, b - a)], i))
    return out


@_register("MATH.G3.NF.EQUIVALENCE_VISUAL")
def _equivalence_visual() -> List[dict]:
    out = []
    data = [(1, 2, 2), (1, 3, 2), (2, 3, 2), (1, 4, 2), (3, 4, 2), (2, 5, 2), (3, 5, 2), (5, 6, 2)]
    for i, (a, b, k) in enumerate(data):
        out.append(_mcq(
            f"A model shows {a}/{b} shaded. Which fraction is equivalent (same amount)?",
            raw(a * k, b * k), [raw(a + k, b + k), raw(a * k, b), raw(a, b * k)], i))
    return out


# ===================== Équivalence / simplification / comparaison =====================

@_register("MATH.G4.NF.EQUIVALENCE_COMPUTE")
def _equivalence_compute() -> List[dict]:
    out = []
    data = [(2, 3, 4), (3, 4, 2), (1, 5, 3), (2, 7, 2), (3, 5, 4), (5, 6, 2), (1, 4, 5), (4, 9, 2), (2, 3, 5), (3, 8, 2)]
    for i, (a, b, k) in enumerate(data):
        ans = a * k
        out.append(_mcq(
            f"Find the missing numerator: {a}/{b} = x/{b*k}", str(ans),
            [str(a + k), str(a * k + 1), str(b * k - a)], i))
    return out


@_register("MATH.G4.NF.SIMPLIFY_FRACTION")
def _simplify() -> List[dict]:
    out = []
    data = [(6, 8), (4, 12), (9, 12), (10, 15), (8, 20), (6, 9), (12, 16), (15, 25), (14, 21), (18, 24)]
    for i, (n, d) in enumerate(data):
        fr = Fraction(n, d)
        g = math.gcd(n, d)
        rn, rd = n // g, d // g
        # distracteurs = simplifications ERRONÉES (valeur différente) : retrancher g,
        # ou se tromper d'un cran sur num/dén réduit.
        out.append(_mcq(f"Write {n}/{d} in lowest terms.", fs(fr),
                        [raw(n - g, d - g), raw(rn, max(1, rd - 1)), raw(rn + 1, rd)], i))
    return out


@_register("MATH.G3.NF.COMPARE_SAME_DENOM")
def _compare_same_denom() -> List[dict]:
    out = []
    data = [(3, 5, 7), (2, 4, 5), (5, 8, 6), (1, 3, 4), (4, 7, 9), (2, 5, 8), (3, 4, 10), (6, 8, 12)]
    for i, (a, c, d) in enumerate(data):
        hi, lo = (a, c) if a > c else (c, a)
        out.append(_mcq(f"Which is greater: {raw(a,d)} or {raw(c,d)}?", raw(hi, d),
                        [raw(lo, d), "They are equal", raw(hi, d + 1)], i))
    return out


@_register("MATH.G3.NF.COMPARE_SAME_NUM")
def _compare_same_num() -> List[dict]:
    out = []
    data = [(3, 4, 8), (2, 3, 5), (1, 2, 6), (3, 5, 10), (4, 6, 9), (2, 4, 7), (5, 6, 12), (1, 3, 4)]
    for i, (a, d1, d2) in enumerate(data):
        # même numérateur a, plus petit dénominateur => plus grand
        hi, lo = (d1, d2) if d1 < d2 else (d2, d1)
        out.append(_mcq(f"Which is greater: {raw(a,d1)} or {raw(a,d2)}?", raw(a, hi),
                        [raw(a, lo), "They are equal", raw(a + 1, hi)], i))
    return out


@_register("MATH.G4.NF.COMPARE_BENCHMARK")
def _compare_benchmark() -> List[dict]:
    out = []
    data = [(3, 4), (2, 5), (1, 3), (5, 8), (4, 6), (3, 8), (5, 6), (2, 6), (7, 12), (1, 2)]
    for i, (a, b) in enumerate(data):
        fr = Fraction(a, b)
        rel = "greater than" if fr > Fraction(1, 2) else ("less than" if fr < Fraction(1, 2) else "equal to")
        out.append(_mcq(f"Compared to 1/2, the fraction {raw(a,b)} is…", rel,
                        [x for x in ["greater than", "less than", "equal to"] if x != rel], i))
    return out


@_register("MATH.G4.NF.COMPARE_DIFF_DENOM")
def _compare_diff_denom() -> List[dict]:
    out = []
    data = [(3, 8, 2, 5), (3, 4, 5, 6), (2, 3, 3, 5), (5, 6, 7, 8), (1, 2, 4, 9), (3, 5, 5, 8), (2, 7, 1, 3), (4, 5, 7, 9)]
    for i, (a, b, c, d) in enumerate(data):
        f1, f2 = Fraction(a, b), Fraction(c, d)
        bigger = raw(a, b) if f1 > f2 else raw(c, d)
        out.append(_mcq(f"Which is greater: {raw(a,b)} or {raw(c,d)}?", bigger,
                        [raw(a, b) if bigger != raw(a, b) else raw(c, d), "They are equal",
                         raw(a + c, b + d)], i))
    return out


# ===================== Addition / soustraction même dénominateur =====================

@_register("MATH.G3.NF.ADD_SAME_NOSIMP")
def _add_same_nosimp() -> List[dict]:
    out = []
    # sommes volontairement NON simplifiables (cohérent avec la compétence "no simplify")
    data = [(1, 3, 5), (2, 1, 5), (1, 2, 7), (3, 2, 8), (1, 4, 9), (3, 4, 10), (2, 3, 7), (3, 1, 7), (2, 5, 11), (5, 3, 11)]
    for i, (a, c, d) in enumerate(data):
        s = a + c
        out.append(_mcq(f"What is {raw(a,d)} + {raw(c,d)}?", raw(s, d),
                        [raw(s, 2 * d), raw(a * c, d), raw(s, d + 1)], i))
    return out


@_register("MATH.G4.NF.ADD_SAME_SIMPLIFY")
def _add_same_simplify() -> List[dict]:
    out = []
    data = [(1, 1, 4), (2, 2, 8), (1, 3, 8), (3, 3, 12), (2, 4, 12), (1, 5, 6), (3, 1, 8), (4, 2, 12), (2, 6, 10), (1, 1, 6)]
    for i, (a, c, d) in enumerate(data):
        fr = Fraction(a + c, d)
        # distracteur clé : la somme NON simplifiée (erreur d'élève la plus fréquente)
        out.append(_mcq(f"Add and simplify: {raw(a,d)} + {raw(c,d)}", fs(fr),
                        [raw(a + c, d), raw(a + c, 2 * d), raw(a, d)], i))
    return out


@_register("MATH.G4.NF.ADD_SAME_IMPROPER")
def _add_same_improper() -> List[dict]:
    out = []
    data = [(3, 2, 4), (5, 3, 6), (4, 5, 8), (7, 4, 8), (2, 3, 4), (5, 4, 6), (6, 5, 8), (3, 4, 5), (7, 6, 10), (5, 5, 6)]
    for i, (a, c, d) in enumerate(data):
        fr = Fraction(a + c, d)
        out.append(_mcq(f"Add (give a mixed number): {raw(a,d)} + {raw(c,d)}", mixed(fr),
                        [raw(a + c, d), raw(a + c, 2 * d), mixed(Fraction(a + c - 1, d))], i))
    return out


@_register("MATH.G3.NF.SUB_SAME_NOSIMP")
def _sub_same_nosimp() -> List[dict]:
    out = []
    data = [(4, 1, 5), (3, 1, 5), (5, 2, 7), (6, 1, 8), (7, 2, 9), (5, 3, 11), (4, 3, 7), (6, 5, 13), (8, 3, 11), (5, 1, 9)]
    for i, (a, c, d) in enumerate(data):
        s = a - c
        out.append(_mcq(f"What is {raw(a,d)} − {raw(c,d)}?", raw(s, d),
                        [raw(s, 0 if False else d - 1), raw(a + c, d), raw(s, 2 * d)], i))
    return out


@_register("MATH.G4.NF.SUB_SAME_SIMPLIFY")
def _sub_same_simplify() -> List[dict]:
    out = []
    data = [(3, 1, 4), (5, 1, 6), (7, 3, 8), (5, 1, 10), (7, 1, 8), (5, 3, 6), (9, 3, 12), (7, 1, 4), (11, 5, 12), (5, 1, 8)]
    for i, (a, c, d) in enumerate(data):
        fr = Fraction(a - c, d)
        out.append(_mcq(f"Subtract and simplify: {raw(a,d)} − {raw(c,d)}", fs(fr),
                        [raw(a - c, d), raw(a - c, 2 * d), raw(a + c, d)], i))
    return out


# ===================== Dénominateurs différents =====================

@_register("MATH.G4.NF.COMMON_DENOM")
def _common_denom() -> List[dict]:
    out = []
    pairs = [(2, 3), (3, 4), (4, 6), (2, 5), (3, 8), (6, 9), (4, 10), (5, 6), (3, 5), (8, 12)]
    for i, (b, d) in enumerate(pairs):
        l = math.lcm(b, d)
        out.append(_mcq(f"What is the least common denominator for {raw(1,b)} and {raw(1,d)}?",
                        str(l), [str(b + d), str(b * d) if b * d != l else str(b * d + 1), str(math.gcd(b, d))], i))
    return out


def _add_unlike(a, b, c, d, *, mixed_out=False):
    fr = Fraction(a, b) + Fraction(c, d)
    L = math.lcm(b, d)
    correct = mixed(fr) if mixed_out else fs(fr)
    distractors = [
        raw(a + c, b + d),               # erreur : additionner numérateurs ET dénominateurs
        raw(a + c, L),                   # bon dénom commun, oubli de convertir les numérateurs
        raw(a * d + c * b, b * d),       # somme correcte mais NON réduite (raw, pas via Fraction)
    ]
    distractors = [x for x in distractors if x != correct]
    return correct, distractors


@_register("MATH.G4.NF.ADD_UNLIKE_SIMPLE")
def _add_unlike_simple() -> List[dict]:
    out = []
    data = [(1, 2, 1, 4), (1, 3, 1, 6), (1, 2, 3, 8), (2, 3, 1, 6), (1, 4, 3, 8),
            (1, 5, 3, 10), (1, 2, 1, 6), (2, 5, 1, 10), (1, 3, 4, 9), (3, 4, 1, 8)]
    for i, (a, b, c, d) in enumerate(data):
        correct, dis = _add_unlike(a, b, c, d)
        out.append(_mcq(f"What is {raw(a,b)} + {raw(c,d)}? (give simplest form)", correct, dis, i))
    return out


@_register("MATH.G4.NF.ADD_UNLIKE_LCM")
def _add_unlike_lcm() -> List[dict]:
    out = []
    data = [(1, 6, 1, 8), (2, 3, 1, 4), (1, 4, 2, 6), (3, 8, 1, 6), (1, 3, 2, 5),
            (2, 5, 1, 4), (1, 6, 3, 8), (3, 4, 1, 6), (2, 9, 1, 6), (1, 8, 1, 12)]
    for i, (a, b, c, d) in enumerate(data):
        correct, dis = _add_unlike(a, b, c, d)
        out.append(_mcq(f"What is {raw(a,b)} + {raw(c,d)}? (give simplest form)", correct, dis, i))
    return out


@_register("MATH.G5.NF.ADD_UNLIKE_FULL")
def _add_unlike_full() -> List[dict]:
    out = []
    data = [(5, 6, 7, 8), (3, 4, 5, 6), (5, 8, 3, 4), (2, 3, 5, 6), (7, 8, 5, 6),
            (3, 5, 5, 6), (5, 6, 3, 8), (7, 10, 4, 5), (5, 8, 7, 12), (2, 3, 3, 4)]
    for i, (a, b, c, d) in enumerate(data):
        correct, dis = _add_unlike(a, b, c, d, mixed_out=True)
        out.append(_mcq(f"What is {raw(a,b)} + {raw(c,d)}? (mixed number, simplest form)", correct, dis, i))
    return out


@_register("MATH.G5.NF.SUB_UNLIKE_LCM")
def _sub_unlike_lcm() -> List[dict]:
    out = []
    data = [(3, 4, 1, 6), (5, 6, 1, 4), (2, 3, 1, 5), (7, 8, 1, 6), (5, 6, 3, 8),
            (3, 5, 1, 4), (5, 8, 1, 6), (4, 5, 1, 3), (7, 10, 1, 4), (5, 6, 2, 9)]
    for i, (a, b, c, d) in enumerate(data):
        fr = Fraction(a, b) - Fraction(c, d)
        L = math.lcm(b, d)
        correct = fs(fr)
        dis = [raw(abs(a - c), abs(b - d) or 1), raw(a - c, L),
               raw(a * d - c * b, b * d)]  # différence correcte mais NON réduite
        dis = [x for x in dis if x != correct]
        out.append(_mcq(f"What is {raw(a,b)} − {raw(c,d)}? (simplest form)", correct, dis, i))
    return out


# ===================== Nombres mixtes =====================

@_register("MATH.G5.NF.MIXED_TO_IMPROPER")
def _mixed_to_improper() -> List[dict]:
    out = []
    data = [(2, 1, 3), (1, 3, 4), (3, 2, 5), (2, 5, 6), (1, 1, 2), (4, 1, 3), (2, 3, 8), (3, 1, 4), (1, 5, 6), (2, 2, 7)]
    for i, (w, n, d) in enumerate(data):
        num = w * d + n
        out.append(_mcq(f"Convert {w} {raw(n,d)} to an improper fraction.", raw(num, d),
                        [raw(w * n, d), raw(w + n, d), raw(num, d + w)], i))
    return out


@_register("MATH.G5.NF.IMPROPER_TO_MIXED")
def _improper_to_mixed() -> List[dict]:
    out = []
    data = [(7, 3), (9, 4), (11, 5), (17, 6), (5, 2), (13, 4), (10, 3), (19, 8), (7, 2), (14, 5)]
    for i, (n, d) in enumerate(data):
        fr = Fraction(n, d)
        w = n // d
        r = n - w * d
        out.append(_mcq(f"Convert {raw(n,d)} to a mixed number.", mixed(fr),
                        [f"{w} {raw(d, r)}" if r else f"{w} 1/{d}",
                         f"{r} {raw(w, d)}", f"{w} {raw(r, d + 1)}"], i))
    return out


@_register("MATH.G5.NF.ADD_MIXED")
def _add_mixed() -> List[dict]:
    out = []
    data = [(2, 1, 4, 1, 1, 4), (1, 1, 3, 2, 1, 3), (2, 3, 8, 1, 1, 8), (1, 1, 6, 1, 1, 6),
            (3, 1, 5, 1, 2, 5), (2, 1, 2, 1, 1, 4), (1, 1, 3, 1, 1, 6), (2, 2, 5, 1, 1, 5),
            (1, 3, 4, 2, 1, 4), (2, 1, 6, 1, 1, 3)]
    for i, (w1, n1, d1, w2, n2, d2) in enumerate(data):
        fr = Fraction(w1 * d1 + n1, d1) + Fraction(w2 * d2 + n2, d2)
        correct = mixed(fr)
        wrong = mixed(Fraction((w1 + w2) * 1) + Fraction(n1 + n2, d1 + d2))  # erreur dén
        out.append(_mcq(f"What is {w1} {raw(n1,d1)} + {w2} {raw(n2,d2)}? (mixed number)", correct,
                        [wrong, f"{w1 + w2} {raw(n1 + n2, d1)}", mixed(fr + 1)], i))
    return out


def generate_for(code: str, count: int = 0) -> List[dict]:
    """Items déterministes pour une compétence (tous, ou les `count` premiers)."""
    gen = GENERATORS.get(code)
    if gen is None:
        return []
    return _take(gen(), count)


def all_codes() -> List[str]:
    return list(GENERATORS.keys())


# ===================== Features de difficulté (savoir-métier FRACTIONS) =====================
# La couche générique (src/items/difficulty.py) mappe la complexité [0,1] sur l'échelle Elo.
# Ici on ne fait QUE produire des features de fractions + une complexité — pluggable par matière.

from src.items.difficulty import difficulty_from_score, weighted_score  # noqa: E402

FRACTION_FEATURE_WEIGHTS = {
    "denom_norm": 0.30,         # taille des dénominateurs
    "needs_lcm": 0.25,          # PPCM requis (dénominateurs sans relation simple)
    "simplify_required": 0.20,  # résultat à réduire
    "improper_result": 0.15,    # résultat > 1 (impropre / mixte)
    "mixed_numbers": 0.20,      # opérandes en nombres mixtes
    "magnitude_norm": 0.30,     # taille des nombres (faits, PPCM/PGCD…)
}

_INT_RE = re.compile(r"\b(\d+)\b")


def _parse_fracs(text: str):
    return [(int(w or 0), int(n), int(d)) for w, n, d in re.findall(r"(?:(\d+)\s+)?(\d+)/(\d+)", text)]


def fraction_features(code: str, content: dict) -> dict:
    """Extrait des `context_tags` PORTEURS DE SENS d'un item de fractions.

    Lisibles par l'humain et exploitables par le moteur (patterns de difficulté
    par contexte, sans fragmenter le graphe).
    """
    stem = content["stem"]
    fracs = _parse_fracs(stem)
    feats: dict = {}

    if fracs:
        dens = [d for _, _, d in fracs]
        feats["max_denominator"] = max(dens)
        feats["unlike_denominators"] = len(set(dens)) > 1
        feats["mixed_numbers"] = any(w > 0 for w, _, _ in fracs)
        if len(dens) >= 2:
            b, d = dens[0], dens[1]
            feats["needs_lcm"] = (b != d) and (b % d != 0) and (d % b != 0)

    op = "add" if "+" in stem else ("sub" if ("−" in stem or " - " in stem) else None)
    if op and len(fracs) >= 2:
        (w1, n1, d1), (w2, n2, d2) = fracs[0], fracs[1]
        x, y = Fraction(w1) + Fraction(n1, d1), Fraction(w2) + Fraction(n2, d2)
        res = x + y if op == "add" else x - y
        feats["operation"] = op
        feats["improper_result"] = res > 1
        if feats.get("unlike_denominators"):
            nn, nd = (n1 * d2 + (n2 * d1 if op == "add" else -n2 * d1)), d1 * d2
        else:
            nn, nd = (n1 + (n2 if op == "add" else -n2)), d1
        feats["simplify_required"] = nd != 0 and math.gcd(abs(nn), nd) > 1

    if not fracs:  # familles « nombres » (faits, facteurs, PPCM, PGCD)
        ints = [int(x) for x in _INT_RE.findall(stem)]
        if ints:
            feats["max_number"] = max(ints)

    return feats


def fraction_complexity(feats: dict) -> float:
    """Complexité [0,1] d'un item de fractions, à partir de ses features."""
    norm = {
        "denom_norm": (min(feats["max_denominator"], 12) / 12) if "max_denominator" in feats else None,
        "needs_lcm": feats.get("needs_lcm"),
        "simplify_required": feats.get("simplify_required"),
        "improper_result": feats.get("improper_result"),
        "mixed_numbers": feats.get("mixed_numbers"),
        "magnitude_norm": (min(feats["max_number"], 100) / 100) if "max_number" in feats else None,
    }
    return weighted_score(norm, FRACTION_FEATURE_WEIGHTS)


def bank_items(code: str, base_prior: float) -> List[dict]:
    """Items prêts pour l'insertion : content + context_tags + difficulty_prior par item.

    C'est ici que se branche la couche générique de difficulté.
    """
    out = []
    for i, content in enumerate(generate_for(code)):
        feats = fraction_features(code, content)
        diff = difficulty_from_score(base_prior, fraction_complexity(feats))
        out.append({"content": content, "context_tags": feats, "difficulty_prior": diff,
                    # Refonte A2 : gabarit = générateur (code) + rang dans sa liste — stable
                    # tant que l'ordre des données du générateur ne change pas.
                    "template_key": template_key(code, i)})
    return out


def template_key(code: str, index: int) -> str:
    """Clé de gabarit d'un item déterministe : `MATH.G4.NF.ADD_LIKE#03`."""
    return f"{code}#{index:02d}"
