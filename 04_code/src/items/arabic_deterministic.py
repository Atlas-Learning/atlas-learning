"""Version arabe DÉTERMINISTE des items de gabarit (refonte A3, invariant 2).

Les générateurs de `deterministic.py` produisent un nombre fini de formes d'énoncé anglais.
Chacune a ici son gabarit arabe (arabe standard moderne, registre scolaire GCC). Les nombres,
fractions et opérateurs restent IDENTIQUES et en chiffres occidentaux 0-9 (convention E7 :
les maths restent LTR). Aucun appel LLM : une correction de wording arabe se fait ici, dans
le code, et se propage par `scripts/regenerate_template.py` comme pour l'anglais.

Statut produit : la machine PROPOSE (`content_ar`, `ar_validated=False`), le linguiste VALIDE
(`review.validate_arabic`) — le gate `ar_validated` reste la seule porte vers le pool servi.
Un rendu qui ne passerait pas `ar_fidelity_errors` n'est jamais proposé (`None`).

Relecture par un locuteur natif : planifiée dans le bucket de la première passe bêta
(docs/refonte/07-tests-beta.md) ; elle se fait ici, dans `_STEMS` et `_OPTIONS`.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from src.items.arabic import ar_fidelity_errors

# Un nombre tel qu'il apparaît dans les énoncés : « 2 1/4 », « 3/8 », « 12 », « 1.5 ».
_NUM = r"((?:\d+\s+)?\d+/\d+|\d+(?:\.\d+)?)"

# (gabarit EN, gabarit AR). Les {n} se correspondent dans l'ordre d'apparition.
_STEMS: List[Tuple[str, str]] = [
    ("A bar is divided into {n} equal parts and {n} parts are shaded. What fraction is shaded?",
     "قُسِّم شريط إلى {n} أجزاء متساوية ولُوِّن {n} منها. ما الكسر الملوَّن؟"),
    ("A circle is cut into {n} equal parts. What fraction is ONE part?",
     "قُطِعت دائرة إلى {n} أجزاء متساوية. ما الكسر الذي يمثّله جزء واحد؟"),
    ("A pizza is cut into {n} equal parts. What fraction is ONE part?",
     "قُطِعت بيتزا إلى {n} أجزاء متساوية. ما الكسر الذي يمثّله جزء واحد؟"),
    ("A rectangle is cut into {n} equal parts. What fraction is ONE part?",
     "قُطِع مستطيل إلى {n} أجزاء متساوية. ما الكسر الذي يمثّله جزء واحد؟"),
    ("A square is cut into {n} equal parts. What fraction is ONE part?",
     "قُطِع مربّع إلى {n} أجزاء متساوية. ما الكسر الذي يمثّله جزء واحد؟"),
    ("A whole is split into {n} equal parts. What fraction is ONE part?",
     "قُسِّم كلٌّ إلى {n} أجزاء متساوية. ما الكسر الذي يمثّله جزء واحد؟"),
    ("A model shows {n} shaded. Which fraction is equivalent (same amount)?",
     "يُظهر نموذج {n} ملوَّنًا. أي كسر يكافئه (الكمية نفسها)؟"),
    ("A number line from {n} to {n} is split into {n} equal intervals. What fraction is at the {n}st tick after {n}?",
     "خط أعداد من {n} إلى {n} مقسَّم إلى {n} فترات متساوية. ما الكسر الواقع عند العلامة رقم {n} بعد {n}؟"),
    ("A number line from {n} to {n} is split into {n} equal intervals. What fraction is at the {n}th tick after {n}?",
     "خط أعداد من {n} إلى {n} مقسَّم إلى {n} فترات متساوية. ما الكسر الواقع عند العلامة رقم {n} بعد {n}؟"),
    ("A set has {n} objects. {n} of them are red. How many are red?",
     "مجموعة فيها {n} أشياء، {n} منها حمراء. كم عدد الأشياء الحمراء؟"),
    ("A whole is divided into {n} equal parts and {n} parts are taken. What fraction is taken?",
     "قُسِّم كلٌّ إلى {n} أجزاء متساوية وأُخِذ {n} منها. ما الكسر المأخوذ؟"),
    ("Add (give a mixed number): {n} + {n}", "اجمع (أعطِ الناتج عددًا كسريًّا): {n} + {n}"),
    ("Add and simplify: {n} + {n}", "اجمع وبسّط: {n} + {n}"),
    ("Subtract and simplify: {n} − {n}", "اطرح وبسّط: {n} − {n}"),
    ("Compared to {n}, the fraction {n} is…", "مقارنةً بـ {n}، الكسر {n} هو…"),
    ("Convert {n} to a mixed number.", "حوِّل {n} إلى عدد كسري."),
    ("Convert {n} to an improper fraction.", "حوِّل {n} إلى كسر غير فعلي."),
    ("Express {n} whole as a fraction with denominator {n}.", "اكتب {n} كاملًا على صورة كسر مقامه {n}."),
    ("Find the missing numerator: {n} = x/{n}", "أوجد البسط الناقص: {n} = x/{n}"),
    ("How many halves make one whole?", "كم نصفًا يصنع كلًّا واحدًا؟"),
    ("How many quarters make one whole?", "كم ربعًا يصنع كلًّا واحدًا؟"),
    ("Two quarters make which fraction?", "ربعان معًا يصنعان أي كسر؟"),
    ("Which fraction means one half?", "أي كسر يعني النصف؟"),
    ("Which fraction means one quarter?", "أي كسر يعني الربع؟"),
    ("What is the greatest common divisor of {n} and {n}?", "ما القاسم المشترك الأكبر للعددين {n} و {n}؟"),
    ("What is the least common denominator for {n} and {n}?", "ما المقام المشترك الأصغر للكسرين {n} و {n}؟"),
    ("What is the least common multiple of {n} and {n}?", "ما المضاعف المشترك الأصغر للعددين {n} و {n}؟"),
    ("What is {n} + {n}? (give simplest form)", "ما ناتج {n} + {n}؟ (في أبسط صورة)"),
    ("What is {n} + {n}? (mixed number, simplest form)", "ما ناتج {n} + {n}؟ (عددًا كسريًّا في أبسط صورة)"),
    ("What is {n} + {n}? (mixed number)", "ما ناتج {n} + {n}؟ (عددًا كسريًّا)"),
    ("What is {n} + {n}?", "ما ناتج {n} + {n}؟"),
    ("What is {n} − {n}? (simplest form)", "ما ناتج {n} − {n}؟ (في أبسط صورة)"),
    ("What is {n} − {n}?", "ما ناتج {n} − {n}؟"),
    ("What is {n} × {n}?", "ما ناتج {n} × {n}؟"),
    ("Which is greater: {n} or {n}?", "أيهما أكبر: {n} أم {n}؟"),
    ("Which number is a factor of {n}?", "أي عدد هو عامل للعدد {n}؟"),
    ("Write {n} in lowest terms.", "اكتب {n} في أبسط صورة."),
]

# Options et réponses textuelles (tout le reste est numérique et reste tel quel).
_OPTIONS: Dict[str, str] = {
    "They are equal": "هما متساويان",
    "equal to": "يساوي",
    "greater than": "أكبر من",
    "less than": "أصغر من",
}

_NUMERIC = re.compile(r"^(?:\d+\s+)?\d+/\d+$|^-?\d+(?:\.\d+)?$")


def _compile(en: str) -> re.Pattern:
    parts = [re.escape(p) for p in en.split("{n}")]
    return re.compile("^" + _NUM.join(parts) + "$")


_COMPILED: List[Tuple[re.Pattern, str]] = [(_compile(en), ar) for en, ar in _STEMS]


def render_stem(stem_en: str) -> Optional[str]:
    """Énoncé arabe d'un énoncé anglais de gabarit, ou None s'il n'a pas de gabarit."""
    stem_en = (stem_en or "").strip()
    for pat, ar in _COMPILED:
        m = pat.match(stem_en)
        if m:
            out = ar
            for value in m.groups():
                out = out.replace("{n}", value, 1)
            return out
    return None


def render_option(text: str) -> Optional[str]:
    text = (text or "").strip()
    if _NUMERIC.match(text):
        return text
    return _OPTIONS.get(text)


def render_arabic(content_en: dict) -> Optional[dict]:
    """`content_ar` déterministe pour un `content_en` de gabarit — ou None si une forme est
    inconnue ou si le rendu échoue aux contrôles de fidélité (jamais de proposition cassée)."""
    stem = render_stem(str(content_en.get("stem", "")))
    if stem is None:
        return None
    options_en = list(content_en.get("options") or [])
    options: List[str] = []
    for o in options_en:
        r = render_option(str(o))
        if r is None:
            return None
        options.append(r)
    answer = render_option(str(content_en.get("answer", "")))
    if answer is None:
        return None
    content_ar: dict = {"stem": stem, "answer": answer}
    if options_en:
        content_ar["options"] = options
    if ar_fidelity_errors(content_en, content_ar):
        return None
    return content_ar


def coverage() -> Tuple[int, int, List[str]]:
    """(rendus, total, énoncés sans gabarit) sur TOUT ce que produisent les générateurs —
    garde-fou de test : un générateur ajouté sans gabarit arabe se voit tout de suite."""
    from src.items import deterministic
    total, done, missing = 0, 0, []
    for code, gen in deterministic.GENERATORS.items():
        for item in gen():
            total += 1
            if render_arabic(item) is not None:
                done += 1
            else:
                missing.append(f"{code}: {item['stem']}")
    return done, total, missing
