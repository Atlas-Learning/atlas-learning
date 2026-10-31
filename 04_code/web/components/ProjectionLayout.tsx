"use client";

import { useLang } from "@/components/LanguageProvider";
import { cx } from "@/components/ui";
import type { CheckInProgress } from "@/lib/types";

/**
 * Mise en page projetable (E2) : code en très grand, compteurs lisibles de loin, une tuile
 * anonyme par élève (invariant 5 : aucun nom, aucun identifiant — le serveur n'en envoie pas).
 */
export function ProjectionLayout({
  code,
  progress,
  fullscreen,
  children,
}: {
  code: string | null;
  progress: CheckInProgress | null;
  fullscreen?: boolean;
  children?: React.ReactNode;
}) {
  const { t } = useLang();
  const c = progress?.counts;
  return (
    <div className={cx("rounded-3xl bg-brand-800 text-white", fullscreen ? "fixed inset-0 z-50 overflow-auto rounded-none p-10" : "p-6 sm:p-8")}>
      <div className="grid gap-8 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <p className="text-sm uppercase tracking-widest text-brand-100/70">{t("checkin.code")}</p>
          <p className={cx("num mt-2 font-semibold tracking-[0.25em]", fullscreen ? "text-[9rem] leading-none" : "text-7xl")} data-ltr>
            {code ?? "····"}
          </p>
          <p className="mt-3 max-w-xs text-sm text-brand-100/80">{t("checkin.code.hint")}</p>
          {c && (
            <dl className={cx("mt-8 grid grid-cols-2 gap-3", fullscreen && "text-lg")}>
              {(["joined", "in_progress", "finished", "absent"] as const).map((k) => (
                <div key={k} className="rounded-2xl bg-white/10 px-4 py-3">
                  <dt className="text-xs uppercase tracking-wide text-brand-100/70">{t(`checkin.${k === "in_progress" ? "inprogress" : k}` as "checkin.joined")}</dt>
                  <dd className="num mt-1 text-3xl font-semibold">{c[k]}<span className="text-base font-normal text-brand-100/60"> / {c.expected}</span></dd>
                </div>
              ))}
            </dl>
          )}
        </div>
        <div className="lg:col-span-3">
          <p className="mb-3 text-xs text-brand-100/70">{t("checkin.tiles.hint")}</p>
          <div className={cx("grid gap-2", fullscreen ? "grid-cols-8" : "grid-cols-6 sm:grid-cols-8")}>
            {(progress?.tiles ?? []).map((tile, i) => (
              <div
                key={i}
                className={cx(
                  "aspect-square rounded-xl ring-1 ring-white/10",
                  tile.state === "finished" && "bg-teal-400",
                  tile.state === "in_progress" && "bg-gold-300",
                  tile.state === "absent" && "bg-white/10",
                )}
                title={tile.state}
              >
                {tile.state !== "absent" && (
                  <span className="num flex h-full items-center justify-center text-sm font-semibold text-brand-900/80">{tile.n_answered}</span>
                )}
              </div>
            ))}
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}
