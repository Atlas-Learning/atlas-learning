"use client";

import { useLang } from "@/components/LanguageProvider";
import { Card, Chip, cx } from "@/components/ui";
import { MasteryRange } from "@/components/MasteryRange";
import type { ProofCardData, ProofRow } from "@/lib/types";

const OUTCOME_CHIP: Record<ProofRow["outcome"], string> = {
  unlocked: "bg-gold-50 text-gold-800 ring-gold-300",          // or : accomplissement
  unchanged: "bg-sand-100 text-sand-600 ring-sand-300",
  not_rechecked: "bg-sand-50 text-sand-400 ring-sand-200",
};

/**
 * Carte de preuve (E4) : « X sur Y ont débloqué » (re-mesurés seulement), puis par élève
 * avant → après avec fourchette, issue en trois états, suggestion. Pas de rouge.
 */
export function ProofCard({ proof, showNames = true }: { proof: ProofCardData; showNames?: boolean }) {
  const { t, lang } = useLang();
  const h = proof.header;
  return (
    <Card className="space-y-5 p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="num text-3xl font-semibold text-sand-800">
            {proof.computed ? t("proof.header").replace("{x}", String(h.unlocked)).replace("{y}", String(h.rechecked)) : "—"}
          </p>
          <p className="mt-1 text-xs text-sand-500">{proof.computed ? t("proof.header.hint") : t("proof.pending")}</p>
        </div>
        {proof.loop_closed && <Chip className="bg-teal-50 text-teal-700 ring-teal-100">{t("proof.loop")}</Chip>}
      </div>

      <ul className="divide-y divide-sand-100">
        {proof.students.map((r) => (
          <li key={r.student_id} className="grid gap-3 py-3 sm:grid-cols-12 sm:items-center">
            <div className="sm:col-span-2">
              <p className="num text-sm font-medium text-sand-800">{showNames ? r.external_ref ?? "—" : "•"}</p>
              <Chip className={cx("mt-1", OUTCOME_CHIP[r.outcome])}>{t(`proof.${r.outcome}` as "proof.unlocked")}</Chip>
            </div>
            <div className="sm:col-span-4">
              <p className="mb-1 text-[11px] uppercase tracking-wide text-sand-400">{t("proof.before")}</p>
              <MasteryRange elo={r.before.elo} state={r.before.elo >= 1500 ? "mastered" : "progress"} estimated={!r.before.measured} compact />
            </div>
            <div className="sm:col-span-4">
              <p className="mb-1 text-[11px] uppercase tracking-wide text-sand-400">{t("proof.after")}</p>
              {r.after ? (
                <MasteryRange elo={r.after.elo} lo={r.after.ci_low} hi={r.after.ci_high}
                  state={r.outcome === "unlocked" ? "mastered" : "progress"} estimated={!r.after.measured} compact />
              ) : (
                <div className="h-2 w-full rounded-full bg-sand-100" data-ltr />
              )}
            </div>
            <div className="text-xs text-sand-600 sm:col-span-2" dir="auto">
              {r.suggestion?.kind === "upstream_cause" && r.suggestion.competency && (
                <>
                  {t("proof.sugg.upstream")} <span className="font-medium">{lang === "ar" ? r.suggestion.competency.label_ar : r.suggestion.competency.label_en}</span>
                </>
              )}
              {r.suggestion?.kind === "practise_again" && t("proof.sugg.practise")}
              {r.suggestion?.kind === "add_to_next_recheck" && t("proof.sugg.next")}
            </div>
          </li>
        ))}
      </ul>
      {proof.computed && <p className="text-xs text-sand-400">{t("proof.interval")}</p>}
    </Card>
  );
}
