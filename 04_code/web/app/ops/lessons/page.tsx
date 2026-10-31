"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Button, Card, Chip, ErrorPanel, Loading, SectionTitle, cx } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Lesson, LessonCoverage, LessonStep, LessonSummary } from "@/lib/types";
import type { DictKey } from "@/lib/i18n";

// O5 · Éditeur de mini-leçons côté Atlas (relecteur, super admin). Même validation que les
// fichiers data/lessons/*.json ; la couverture des causes racines (Q3) guide la rédaction.
export default function LessonsPage() {
  return (
    <AppShell>
      <LessonsView />
    </AppShell>
  );
}

const KINDS: LessonStep["kind"][] = ["warmup", "model", "guided", "exit"];
const STATUS_CHIP: Record<string, string> = {
  draft: "bg-sand-100 text-sand-600 ring-sand-300",
  linguist_validated: "bg-brand-50 text-brand-700 ring-brand-200",
  active: "bg-teal-50 text-teal-700 ring-teal-100",
};

type Draft = { id?: string; competency: string; title_en: string; title_ar: string; duration_min: number; version: number; steps: LessonStep[] };

function emptyDraft(competency = ""): Draft {
  return {
    competency, title_en: "", title_ar: "", duration_min: 12, version: 1,
    steps: [
      { kind: "warmup", minutes: 2, body_en: "", body_ar: "" },
      { kind: "model", minutes: 4, body_en: "", body_ar: "" },
      { kind: "guided", minutes: 4, body_en: "", body_ar: "" },
      { kind: "exit", minutes: 2, body_en: "", body_ar: "" },
    ],
  };
}

function LessonsView() {
  const { t, lang } = useLang();
  const [lessons, setLessons] = useState<LessonSummary[] | null>(null);
  const [coverage, setCoverage] = useState<LessonCoverage[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.opsLessons().then((r) => { setLessons(r.lessons); setCoverage(r.coverage); })
      .catch((e) => setError(e instanceof ApiError ? e.detail : (e as Error).message));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function edit(id: string) {
    const l: Lesson = await api.lesson(id);
    setDraft({ id: l.id, competency: l.competency?.code ?? "", title_en: l.title_en, title_ar: l.title_ar ?? "",
      duration_min: l.duration_min, version: l.version, steps: l.steps.map((s) => ({ ...s, body_ar: s.body_ar ?? "" })) });
  }

  async function save() {
    if (!draft) return;
    setBusy(true); setError(null); setNotice(null);
    const body = {
      competency: draft.competency.trim(), title_en: draft.title_en.trim(), title_ar: draft.title_ar.trim() || null,
      duration_min: Number(draft.duration_min), version: Number(draft.version),
      steps: draft.steps.filter((s) => s.body_en.trim()).map((s) => ({ kind: s.kind, minutes: Number(s.minutes), body_en: s.body_en.trim(), body_ar: (s.body_ar ?? "").trim() || null })),
    };
    try {
      if (draft.id) await api.opsLessonUpdate(draft.id, body); else await api.opsLessonCreate(body);
      setNotice(t("lessons.saved")); setDraft(null); load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message);
    } finally { setBusy(false); }
  }

  if (error && !draft) return <ErrorPanel detail={error} />;
  if (!lessons) return <Loading label={t("common.loading")} />;
  const label = (c: { label_en: string; label_ar: string }) => (lang === "ar" ? c.label_ar : c.label_en);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-sand-800">{t("lessons.title")}</h1>
          <p className="mt-1 text-sm text-sand-500">{t("lessons.subtitle")}</p>
        </div>
        {!draft && <Button variant="accent" onClick={() => setDraft(emptyDraft())}>{t("lessons.new")}</Button>}
      </header>
      {notice && <p className="rounded-lg bg-teal-50 px-3 py-2 text-sm text-teal-700">{notice}</p>}

      {draft ? (
        <Card className="space-y-4 p-5">
          <SectionTitle title={draft.id ? t("lessons.edit") : t("lessons.new")} />
          {error && <p className="text-sm text-danger" dir="auto">{error}</p>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("lessons.field.competency")}>
              <input list="comps" value={draft.competency} onChange={(e) => setDraft({ ...draft, competency: e.target.value })} className={INPUT} data-ltr />
              <datalist id="comps">{coverage.map((c) => <option key={c.code} value={c.code}>{label(c)}</option>)}</datalist>
            </Field>
            <Field label={t("lessons.field.title")}><input value={draft.title_en} onChange={(e) => setDraft({ ...draft, title_en: e.target.value })} className={INPUT} /></Field>
            <Field label={t("lessons.field.title_ar")}><input value={draft.title_ar} onChange={(e) => setDraft({ ...draft, title_ar: e.target.value })} className={INPUT} dir="rtl" /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("lessons.field.duration")}><input type="number" min={1} max={60} value={draft.duration_min} onChange={(e) => setDraft({ ...draft, duration_min: Number(e.target.value) })} className={INPUT} /></Field>
              <Field label={t("lessons.field.version")}><input type="number" min={1} value={draft.version} onChange={(e) => setDraft({ ...draft, version: Number(e.target.value) })} className={INPUT} disabled={!!draft.id} /></Field>
            </div>
          </div>
          <ol className="space-y-3">
            {draft.steps.map((st, i) => (
              <li key={KINDS[i]} className="rounded-xl border border-sand-200 p-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">{t(`group.step.${st.kind}` as DictKey)}</p>
                  <label className="flex items-center gap-1 text-xs text-sand-500">
                    <input type="number" min={1} max={60} value={st.minutes} className="num w-14 rounded-md border border-sand-300 px-2 py-1 text-sm"
                      onChange={(e) => setDraft({ ...draft, steps: draft.steps.map((x, j) => j === i ? { ...x, minutes: Number(e.target.value) } : x) })} />
                    {t("lessons.field.minutes")}
                  </label>
                </div>
                <textarea rows={3} value={st.body_en} placeholder={t("lessons.field.body_en")} className={cx(INPUT, "mt-2")}
                  onChange={(e) => setDraft({ ...draft, steps: draft.steps.map((x, j) => j === i ? { ...x, body_en: e.target.value } : x) })} />
                <textarea rows={2} value={st.body_ar ?? ""} placeholder={t("lessons.field.body_ar")} className={cx(INPUT, "mt-2 font-ar")} dir="rtl"
                  onChange={(e) => setDraft({ ...draft, steps: draft.steps.map((x, j) => j === i ? { ...x, body_ar: e.target.value } : x) })} />
              </li>
            ))}
          </ol>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => { setDraft(null); setError(null); }} disabled={busy}>{t("lessons.cancel")}</Button>
            <Button variant="accent" onClick={save} disabled={busy || !draft.competency || !draft.title_en}>{t("lessons.save")}</Button>
          </div>
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-5">
          <Card className="p-5 lg:col-span-3">
            <SectionTitle title={t("lessons.coverage")} />
            <ul className="divide-y divide-sand-100">
              {coverage.map((c) => (
                <li key={c.code} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-sand-800">{label(c)}</p>
                    <p className="num text-xs text-sand-400" data-ltr>{c.code} · G{c.grade} · {t("lessons.coverage.unlocks")} {c.unlocks}</p>
                  </div>
                  {c.best_status ? (
                    <Chip className={STATUS_CHIP[c.best_status]}>{c.best_status}</Chip>
                  ) : (
                    <Button variant="outline" onClick={() => setDraft(emptyDraft(c.code))}>{t("lessons.coverage.none")} → {t("lessons.new")}</Button>
                  )}
                </li>
              ))}
            </ul>
          </Card>
          <Card className="p-5 lg:col-span-2">
            <SectionTitle title={t("lessons.all")} />
            <ul className="space-y-2">
              {lessons.map((l) => (
                <li key={l.id} className="rounded-xl border border-sand-200 p-3">
                  <p className="text-sm font-medium text-sand-800">{l.title_en}</p>
                  <p className="num mt-0.5 text-xs text-sand-400" data-ltr>{l.key} · {l.duration_min} min</p>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <Chip className={STATUS_CHIP[l.status]}>{l.status}{l.arabic_complete ? " · AR ✓" : ""}</Chip>
                    <div className="flex gap-1">
                      <Button variant="ghost" onClick={() => edit(l.id)}>{t("lessons.edit")}</Button>
                      {l.status === "linguist_validated" && (
                        <Button variant="outline" onClick={async () => { await api.lessonActivate(l.id); load(); }}>{t("lessons.activate")}</Button>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}
    </div>
  );
}

const INPUT = "w-full rounded-lg border border-sand-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-sand-500">{label}</span>
      {children}
    </label>
  );
}
