"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell, useMe } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Button, Card, Chip, EmptyState, ErrorPanel, Loading, SectionTitle, cx } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { ReviewAction, ReviewDetail, ReviewEntry, ReviewQueue, ReviewSource } from "@/lib/types";
import type { DictKey } from "@/lib/i18n";

// O2 · File de revue (ticket A4) — relecteur de contenu et super admin.
// Une file, quatre sources, regroupée par gabarit ; détail EN/AR côte à côte ; actions selon le
// rôle (le serveur ne liste au relecteur que les siennes) ; rappel du cycle de statuts.
// Référence visuelle : docs/refonte/maquettes/Admin-review.dc.html (reconstruite, pas copiée).

const SOURCES: (ReviewSource | "all")[] = ["all", "flag", "validation", "school", "arabic"];
const SOURCE_KEY: Record<ReviewSource | "all", DictKey> = {
  all: "review.src.all",
  flag: "review.src.flag",
  validation: "review.src.validation",
  school: "review.src.school",
  arabic: "review.src.arabic",
};
const SOURCE_CHIP: Record<ReviewSource, string> = {
  flag: "bg-gold-50 text-gold-700 ring-gold-200",
  validation: "bg-sand-100 text-sand-700 ring-sand-300",
  school: "bg-teal-50 text-teal-700 ring-teal-100",
  arabic: "bg-brand-50 text-brand-700 ring-brand-200",
};
const STATUS_CHIP: Record<string, string> = {
  ai_generated: "bg-sand-100 text-sand-600 ring-sand-300",
  human_reviewed: "bg-brand-50 text-brand-700 ring-brand-200",
  linguist_validated: "bg-teal-50 text-teal-700 ring-teal-100",
  active: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  quarantined: "bg-gold-50 text-gold-700 ring-gold-200",
};

export default function ReviewPage() {
  return (
    <AppShell>
      <ReviewView />
    </AppShell>
  );
}

function ReviewView() {
  const { t } = useLang();
  const [source, setSource] = useState<ReviewSource | "all">("all");
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .opsReview(source === "all" ? undefined : source)
      .then(setQueue)
      .catch((e) => setError(e instanceof ApiError ? e.detail : (e as Error).message));
  }, [source]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <ErrorPanel detail={error} />;
  if (!queue) return <Loading label={t("common.loading")} />;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-sand-800">{t("review.title")}</h1>
        <p className="mt-1 text-sm text-sand-500">{t("review.subtitle")}</p>
      </header>

      {/* Filtres par source, avec compteurs globaux. */}
      <div className="flex flex-wrap gap-2" role="tablist">
        {SOURCES.map((s) => (
          <button
            key={s}
            role="tab"
            aria-selected={s === source}
            onClick={() => {
              setSource(s);
              setSelected(null);
            }}
            className={cx(
              "rounded-lg px-3.5 py-1.5 text-sm font-medium ring-1 transition-colors",
              s === source ? "bg-brand-600 text-white ring-brand-600" : "bg-white text-sand-600 ring-sand-300 hover:bg-sand-50",
            )}
          >
            {t(SOURCE_KEY[s])} <span className="num opacity-80">· {queue.counts[s]}</span>
          </button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Liste regroupée par gabarit. */}
        <div className="space-y-4 lg:col-span-2">
          {queue.groups.length === 0 ? (
            <EmptyState title={t("review.title")} body={t("review.empty")} />
          ) : (
            queue.groups.map((g) => (
              <Card key={g.template ?? "—"} className="p-4">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-sand-800">
                      {g.template ?? t("review.group.notemplate")}
                    </p>
                    <p className="num mt-0.5 text-xs text-sand-500">
                      {g.n_items} {t("review.group.items")} · {g.n_active} {t("review.group.active")}
                      {g.open_flags > 0 ? ` · ${g.open_flags} ${t("review.group.flags")}` : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap justify-end gap-1">
                    {g.sources.map((s) => (
                      <Chip key={s} className={SOURCE_CHIP[s]}>
                        {t(SOURCE_KEY[s])}
                      </Chip>
                    ))}
                  </div>
                </div>
                <ul className="space-y-1">
                  {g.items.map((e) => (
                    <li key={e.item_id}>
                      <button
                        onClick={() => setSelected(e.item_id)}
                        className={cx(
                          "w-full rounded-lg px-3 py-2 text-start text-sm transition-colors",
                          selected === e.item_id ? "bg-brand-50 text-brand-800" : "hover:bg-sand-50 text-sand-700",
                        )}
                      >
                        <span className="block truncate" dir="ltr">
                          {e.stem_en}
                        </span>
                        <span className="num mt-0.5 block text-xs text-sand-400">
                          {e.template_key ?? e.origin} · v{e.version} · {e.status}
                          {e.open_flags > 0 ? ` · ${e.open_flags} ⚑` : ""}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            ))
          )}
        </div>

        {/* Détail EN / AR + actions. */}
        <div className="lg:col-span-3">
          {selected ? (
            <Detail itemId={selected} onChanged={load} key={selected} />
          ) : (
            <Card className="p-5">
              <p className="py-10 text-center text-sm text-sand-400">{t("review.select")}</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function Detail({ itemId, onChanged }: { itemId: string; onChanged: () => void }) {
  const { t } = useLang();
  const me = useMe();
  const isSuper = me?.roles.includes("super_admin") ?? false;
  const [d, setD] = useState<ReviewDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [pending, setPending] = useState<ReviewAction | null>(null);
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(() => {
    api
      .opsReviewItem(itemId)
      .then(setD)
      .catch((e) => setErr(e instanceof ApiError ? e.detail : (e as Error).message));
  }, [itemId]);

  useEffect(() => {
    reload();
  }, [reload]);

  if (err) return <ErrorPanel detail={err} />;
  if (!d) return <Loading label={t("common.loading")} />;

  const run = async (fn: () => Promise<void>, label: string) => {
    setBusy(label);
    setErr(null);
    setNotice(null);
    try {
      await fn();
      setPending(null);
      setReason("");
      reload();
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : (e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const act = (a: ReviewAction) => {
    switch (a) {
      case "approve":
        return run(async () => void (await api.itemTransition(d.item_id, "human_reviewed")), a);
      case "quarantine":
        return run(async () => void (await api.itemTransition(d.item_id, "quarantined", reason || undefined)), a);
      case "rehabilitate":
      case "activate":
        return run(async () => void (await api.itemTransition(d.item_id, "active", reason || undefined)), a);
      case "reject":
        return run(async () => void (await api.itemReject(d.item_id, reason)), a);
      case "quarantine_template":
        return run(async () => {
          const r = await api.opsTemplateQuarantine(d.template!, reason || undefined);
          setNotice(t("review.quarantine.result").replace("{n}", String(r.quarantined.length)));
        }, a);
      case "regenerate":
        return run(async () => {
          const r = await api.opsTemplateRegenerate(d.template!, false);
          setNotice(
            t("review.regen.result")
              .replace("{a}", String(r.regenerated.length))
              .replace("{b}", String(r.created.length))
              .replace("{c}", String(r.unchanged.length)),
          );
        }, a);
      default:
        return Promise.resolve();
    }
  };

  const preview = () =>
    run(async () => {
      const r = await api.opsTemplateRegenerate(d.template!, true);
      setNotice(
        t("review.regen.result")
          .replace("{a}", String(r.regenerated.length))
          .replace("{b}", String(r.created.length))
          .replace("{c}", String(r.unchanged.length)),
      );
    }, "preview");

  const needsReason = (a: ReviewAction) => a === "reject" || a === "quarantine" || a === "quarantine_template";
  const openFlags = d.flags.filter((f) => f.status === "open");
  const answerEn = d.content_en.answer;
  const answerAr = d.content_ar?.answer;

  return (
    <Card className="space-y-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Chip className={STATUS_CHIP[d.status] ?? "bg-sand-100 text-sand-600 ring-sand-300"}>{d.status}</Chip>
            {d.sources.map((s) => (
              <Chip key={s} className={SOURCE_CHIP[s]}>
                {t(SOURCE_KEY[s])}
              </Chip>
            ))}
          </div>
          <p className="num mt-2 text-xs text-sand-500">
            {d.competency_code} · {t("review.item.template")} {d.template_key ?? "—"} · {t("review.item.version")} {d.version} ·{" "}
            {d.n_responses} {t("review.item.responses")}
          </p>
        </div>
      </div>

      {/* EN / AR côte à côte — l'AR en RTL, les maths restent LTR par les chiffres 0-9. */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <p className="text-xs uppercase tracking-wide text-sand-400">{t("review.item.en")}</p>
          <p className="mt-1 text-sm text-sand-800" dir="ltr">
            {d.content_en.stem}
          </p>
          <Options options={d.content_en.options} answer={answerEn} dir="ltr" keyLabel={t("review.item.key")} />
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-sand-400">{t("review.item.ar")}</p>
          {d.content_ar ? (
            <>
              <p className="mt-1 font-ar text-sm text-sand-800" dir="rtl">
                {d.content_ar.stem}
              </p>
              <Options options={d.content_ar.options} answer={answerAr} dir="rtl" keyLabel={t("review.item.key")} />
            </>
          ) : (
            <p className="mt-1 text-sm text-sand-400">{t("review.item.noar")}</p>
          )}
        </div>
      </div>

      {d.validation_errors.length > 0 && (
        <div>
          <SectionTitle title={t("review.item.errors")} />
          <ul className="list-inside list-disc text-sm text-gold-700">
            {d.validation_errors.map((e) => (
              <li key={e} dir="auto">
                {e}
              </li>
            ))}
          </ul>
        </div>
      )}

      {d.flags.length > 0 && (
        <div>
          <SectionTitle title={`${t("review.flags.title")} · ${openFlags.length}/${d.flags.length}`} />
          <ul className="space-y-2">
            {d.flags.map((f) => (
              <li key={f.id} className="flex items-center justify-between gap-3 rounded-lg border border-sand-200 px-3 py-2 text-sm">
                <div>
                  <span className="font-medium text-sand-800">{f.reason}</span>
                  {f.comment && <span className="text-sand-500" dir="auto"> · {f.comment}</span>}
                  <span className="ms-2 text-xs text-sand-400">{f.status}</span>
                </div>
                {f.status === "open" && d.actions.includes("resolve_flag") && (
                  <div className="flex shrink-0 gap-1">
                    <Button variant="ghost" disabled={busy !== null}
                      onClick={() => run(async () => void (await api.itemFlagResolve(f.id, false)), "flag")}>
                      {t("review.flag.reject")}
                    </Button>
                    <Button variant="outline" disabled={busy !== null}
                      onClick={() => run(async () => void (await api.itemFlagResolve(f.id, true)), "flag")}>
                      {t("review.flag.accept")}
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {openFlags.length > 0 && <p className="mt-2 text-xs text-sand-500">{t("review.flag.accept.hint")}</p>}
        </div>
      )}

      {d.versions.length > 1 && (
        <div>
          <SectionTitle title={t("review.versions")} />
          <ul className="num flex flex-wrap gap-2 text-xs">
            {d.versions.map((v) => (
              <li key={v.item_id} className={cx("rounded-lg px-2.5 py-1 ring-1", v.item_id === d.item_id ? "bg-brand-50 text-brand-700 ring-brand-200" : "text-sand-600 ring-sand-300")}>
                v{v.version} · {v.status}{v.deleted ? " · rejected" : ""} · {v.n_responses}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Rappel du cycle de statuts. */}
      <div>
        <SectionTitle title={t("review.lifecycle")} subtitle={t("review.lifecycle.note")} />
        <ol className="num flex flex-wrap items-center gap-1 text-xs text-sand-600" dir="ltr">
          {d.lifecycle.map((st, i) => (
            <li key={st} className="flex items-center gap-1">
              <span className={cx("rounded-md px-2 py-0.5 ring-1", st === d.status ? "bg-brand-600 text-white ring-brand-600" : "ring-sand-300")}>{st}</span>
              {i < d.lifecycle.length - 1 && <span className="text-sand-400">→</span>}
            </li>
          ))}
          <li className="ms-2 rounded-md px-2 py-0.5 ring-1 ring-gold-200 text-gold-700">quarantined</li>
        </ol>
      </div>

      {notice && <p className="rounded-lg bg-teal-50 px-3 py-2 text-sm text-teal-700" dir="auto">{notice}</p>}
      {err && <p className="text-sm text-danger" dir="auto">{err}</p>}

      {/* Actions : seulement celles que le serveur autorise pour ce rôle. */}
      {pending ? (
        <div className="space-y-2 rounded-xl border border-sand-200 bg-sand-25 p-3">
          <p className="text-sm font-medium text-sand-800">{t(`review.action.${pending}` as DictKey)}</p>
          {needsReason(pending) && (
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("review.action.reason")} dir="auto"
              className="w-full rounded-lg border border-sand-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400" />
          )}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setPending(null)} disabled={busy !== null}>{t("ling.cancel")}</Button>
            <Button variant="accent" onClick={() => act(pending)} disabled={busy !== null || (pending === "reject" && !reason.trim())}>
              {t("review.action.confirm")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-end gap-2">
          {d.actions.filter((a) => a !== "resolve_flag").map((a) => (
            <Button key={a} variant={a === "regenerate" || a === "activate" ? "accent" : a === "reject" ? "ghost" : "outline"}
              disabled={busy !== null} onClick={() => (needsReason(a) ? setPending(a) : act(a))}>
              {t(`review.action.${a}` as DictKey)}
            </Button>
          ))}
          {isSuper && d.template && (
            <Button variant="ghost" disabled={busy !== null} onClick={preview}>{t("review.action.regenerate.dry")}</Button>
          )}
          {!isSuper && d.template && <span className="text-xs text-sand-400">{t("review.superonly")}: regenerate</span>}
        </div>
      )}
    </Card>
  );
}

function Options({ options, answer, dir, keyLabel }: { options?: string[]; answer?: string; dir: "ltr" | "rtl"; keyLabel: string }) {
  if (!options || options.length === 0) return null;
  const letters = dir === "rtl" ? ["أ", "ب", "ج", "د", "هـ"] : ["A", "B", "C", "D", "E"];
  return (
    <ul className="mt-2 space-y-1" dir={dir}>
      {options.map((o, i) => (
        <li key={`${o}-${i}`} className={cx("flex items-center justify-between rounded-lg px-2.5 py-1 text-sm", o === answer ? "bg-emerald-50 text-emerald-900" : "text-sand-700")}>
          <span className="num">{letters[i] ?? i + 1} · {o}</span>
          {o === answer && <span className="text-xs text-emerald-700">{keyLabel}</span>}
        </li>
      ))}
    </ul>
  );
}
