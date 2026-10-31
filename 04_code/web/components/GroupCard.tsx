"use client";

import Link from "next/link";
import { useLang } from "@/components/LanguageProvider";
import { Chip, cx } from "@/components/ui";
import { CausalThread } from "@/components/CausalThread";
import type { PlanAction } from "@/lib/types";

/**
 * Carte d'action du plan (E1) : rang, fil causal compact, phrase « parce que », badge
 * mesuré / partiellement estimé, membres, leçon, statut. Une seule action principale : ouvrir.
 */
export function GroupCard({ action, classroomId }: { action: PlanAction; classroomId: string }) {
  const { t, lang } = useLang();
  const because = lang === "ar" ? action.because_ar : action.because_en;
  const label = (c: { label_en: string; label_ar: string }) => (lang === "ar" ? c.label_ar : c.label_en);
  const done = action.status === "done";
  const dismissed = action.status === "dismissed";
  return (
    <li className={cx("rounded-2xl border bg-white p-4 shadow-card", dismissed ? "border-sand-200 opacity-60" : "border-sand-200")}>
      <div className="flex items-start gap-3">
        <span className="num mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-brand-600 text-sm font-semibold text-white">
          {action.rank}
        </span>
        <div className="min-w-0 flex-1 space-y-3">
          <CausalThread mastered={null} root={label(action.root_cause)} shows={label(action.blocked)} compact />
          <p className="text-sm leading-relaxed text-sand-800" dir="auto">{because}</p>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Chip className={action.confidence === "measured" ? "bg-teal-50 text-teal-700 ring-teal-100" : "bg-sand-100 text-sand-600 ring-sand-300"}>
              {action.confidence === "measured" ? t("week.badge.measured") : t("week.badge.partly")}
            </Chip>
            <span className="num text-sand-500">{action.n_members} {t("week.action.members")}</span>
            {action.lesson ? (
              <span className="num text-sand-500">· {action.lesson.duration_min} {t("group.lesson.min")} {t("week.action.lesson")}</span>
            ) : (
              <span className="text-sand-400">· {t("week.action.nolesson")}</span>
            )}
            {done && <Chip className="bg-teal-50 text-teal-700 ring-teal-100">{t("week.action.done")}</Chip>}
            {dismissed && <Chip className="bg-sand-100 text-sand-500 ring-sand-200">{t("week.action.dismissed")}</Chip>}
          </div>
        </div>
        <Link
          href={done ? `/teacher/${classroomId}/actions/${action.id}/proof` : `/teacher/${classroomId}/actions/${action.id}`}
          className="shrink-0 rounded-lg bg-brand-50 px-3 py-1.5 text-sm font-medium text-brand-700 hover:bg-brand-100"
        >
          {done ? t("group.proof") : t("week.action.open")}
        </Link>
      </div>
    </li>
  );
}
