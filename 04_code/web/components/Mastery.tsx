"use client";

import { useLang } from "@/components/LanguageProvider";
import { Chip, cx } from "@/components/ui";
import { StandardBadge } from "@/components/StandardBadge";
import type { CompetencyMastery } from "@/lib/types";
import { abilityToPct, isEstimated, label, masteryState, STATE_STYLE } from "@/lib/mastery";

/** Pastille de confiance — distingue honnêtement mesuré vs estimé (Brief §2). */
export function ConfidenceBadge({ confidence, measured }: { confidence: number; measured: boolean }) {
  const { t } = useLang();
  if (measured && !isEstimated(confidence)) {
    return (
      <Chip className="bg-white text-sand-600 ring-sand-200">
        <span className="h-1.5 w-1.5 rounded-full bg-mastered" /> {t("common.measured")}
      </Chip>
    );
  }
  // Estimé : hachure visuelle pour signaler l'incertitude, jamais un faux score précis.
  return (
    <Chip className="bg-sand-50 text-sand-500 ring-sand-200" >
      <span className="h-1.5 w-1.5 rounded-full bg-unmeasured" /> {t("common.estimated")}
    </Chip>
  );
}

/** Barre de maîtrise — la primitive réutilisée partout. Encode l'état + la confiance. */
export function MasteryBar({
  ability,
  state,
  estimated,
}: {
  ability: number;
  state: "mastered" | "progress" | "unmeasured";
  estimated?: boolean;
}) {
  const pct = abilityToPct(ability);
  const style = STATE_STYLE[state];
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-sand-100" data-ltr>
      <div
        className={cx("bar-fill h-full rounded-full", style.bar, estimated && "opacity-45")}
        style={{
          width: `${pct}%`,
          backgroundImage: estimated
            ? "repeating-linear-gradient(45deg, rgba(255,255,255,.55) 0 4px, transparent 4px 8px)"
            : undefined,
        }}
      />
    </div>
  );
}

/** Carte de compétence : libellé + état + confiance + barre. */
export function CompetencyCard({ c }: { c: CompetencyMastery }) {
  const { lang, t } = useLang();
  const state = masteryState(c);
  const style = STATE_STYLE[state];
  const estimated = isEstimated(c.confidence);
  const stateLabel =
    state === "mastered" ? t("common.mastered") : state === "progress" ? t("common.inprogress") : t("common.notmeasured");

  return (
    <div className="rounded-xl border border-sand-200 bg-white p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-sand-800">{label(c, lang)}</p>
          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-sand-400">
            <span data-ltr>{c.code.replace("MATH.", "")}</span>
            {/* B4 : code standard si vue curriculaire — absent en vue ATLAS. C3 : libellé visible. */}
            <StandardBadge standard={c.standard} showWording />
          </p>
        </div>
        <span className={cx("mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full", style.dot)} title={stateLabel} />
      </div>
      <div className="mt-3">
        <MasteryBar ability={c.ability_elo} state={state} estimated={estimated} />
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className={cx("text-xs font-medium", style.text)}>{stateLabel}</span>
        <ConfidenceBadge confidence={c.confidence} measured={c.measured} />
      </div>
    </div>
  );
}
