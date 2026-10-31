"use client";

import { cx } from "@/components/ui";
import type { CellState } from "@/lib/types";
import { abilityToPct } from "@/lib/mastery";

// Couleurs sémantiques (invariant 9) : teal = maîtrisé, ambre = prochaine étape, sable = non
// mesuré, hachure = estimé. Jamais de rouge pour une lacune.
export const CELL_STYLE: Record<CellState, { bg: string; text: string; dot: string }> = {
  mastered: { bg: "bg-teal-500", text: "text-teal-700", dot: "bg-teal-500" },
  progress: { bg: "bg-gold-400", text: "text-gold-700", dot: "bg-gold-400" },
  estimated: { bg: "bg-sand-300", text: "text-sand-500", dot: "bg-sand-300" },
  unmeasured: { bg: "bg-sand-200", text: "text-sand-400", dot: "bg-sand-200" },
};

const HATCH = "repeating-linear-gradient(45deg, rgba(255,255,255,.6) 0 4px, transparent 4px 8px)";

/**
 * Barre de maîtrise avec fourchette : position de l'estimation, intervalle [lo, hi] en demi-ton,
 * hachurée si l'estimation n'est pas mesurée (confiance basse ou propagée). Repère de maîtrise
 * (1500) tracé. LTR même en RTL (les maths restent LTR : data-ltr).
 */
export function MasteryRange({
  elo,
  lo,
  hi,
  state,
  estimated,
  compact,
}: {
  elo: number | null;
  lo?: number | null;
  hi?: number | null;
  state: CellState;
  estimated?: boolean;
  compact?: boolean;
}) {
  const style = CELL_STYLE[state];
  const pct = elo == null ? null : abilityToPct(elo);
  const mastery = abilityToPct(1500);
  return (
    <div className={cx("relative w-full overflow-hidden rounded-full bg-sand-100", compact ? "h-2" : "h-3")} data-ltr>
      {/* repère de maîtrise */}
      <div className="absolute inset-y-0 w-px bg-sand-400/70" style={{ left: `${mastery}%` }} />
      {pct != null && lo != null && hi != null && (
        <div
          className={cx("absolute inset-y-0 rounded-full opacity-35", style.bg)}
          style={{ left: `${abilityToPct(lo)}%`, width: `${Math.max(2, abilityToPct(hi) - abilityToPct(lo))}%` }}
        />
      )}
      {pct != null && (
        <div
          className={cx("absolute inset-y-0 rounded-full", style.bg)}
          style={{ left: `${Math.max(0, pct - 1.5)}%`, width: "3%", backgroundImage: estimated ? HATCH : undefined }}
        />
      )}
    </div>
  );
}

/** Pastille d'état pour une cellule de matrice ou un membre de groupe. */
export function StateDot({ state, className }: { state: CellState; className?: string }) {
  return (
    <span
      className={cx("inline-block h-3 w-3 rounded-sm", CELL_STYLE[state].dot, className)}
      style={{ backgroundImage: state === "estimated" ? HATCH : undefined }}
    />
  );
}
