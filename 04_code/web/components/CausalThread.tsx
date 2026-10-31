"use client";

import { useLang } from "@/components/LanguageProvider";
import { cx } from "@/components/ui";

/**
 * Fil causal (E6, B5) : maîtrisé → cause racine → où ça se voit. Trois nœuds reliés, lus dans
 * le sens de lecture (la flèche se retourne en RTL via .rtl-flip). Composant héros de la fiche
 * élève, réutilisé en version compacte dans le plan.
 */
export function CausalThread({
  mastered,
  root,
  shows,
  compact,
}: {
  mastered: string | null;
  root: string;
  shows: string | null;
  compact?: boolean;
}) {
  const { t } = useLang();
  const nodes: { key: string; label: string | null; title: string; tone: string }[] = [
    { key: "mastered", label: mastered, title: t("thread.mastered"), tone: "bg-teal-50 text-teal-800 ring-teal-100" },
    { key: "root", label: root, title: t("thread.root"), tone: "bg-gold-50 text-gold-800 ring-gold-200" },
    { key: "shows", label: shows, title: t("thread.shows"), tone: "bg-sand-100 text-sand-700 ring-sand-200" },
  ];
  return (
    <ol className={cx("flex flex-wrap items-stretch", compact ? "gap-1.5" : "gap-2")}>
      {nodes.filter((n) => n.label).map((n, i, arr) => (
        <li key={n.key} className="flex items-center gap-1.5">
          <div className={cx("rounded-xl ring-1", n.tone, compact ? "px-2.5 py-1.5" : "px-3.5 py-2.5")}>
            <p className={cx("uppercase tracking-wide opacity-70", compact ? "text-[10px]" : "text-[11px]")}>{n.title}</p>
            <p className={cx("font-medium", compact ? "text-xs" : "text-sm")}>{n.label}</p>
          </div>
          {i < arr.length - 1 && (
            <svg className="rtl-flip shrink-0 text-sand-400" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </li>
      ))}
    </ol>
  );
}
