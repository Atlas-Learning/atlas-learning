"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useLang } from "@/components/LanguageProvider";
import { Button, Card, Chip, EmptyState, ErrorPanel, Loading, SectionTitle, cx } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type {
  AlignmentType,
  FrameworkCoverage,
  CurriculumDetail,
  CurriculumFrameworkRow,
  CurriculumMappingRow,
  CurriculumStandardRow,
  GraphNode,
  MappingConfidence,
  StandardState,
} from "@/lib/types";
import type { DictKey } from "@/lib/i18n";

// O3 · Mapping d'un curriculum (refonte C3) — super admin uniquement (le serveur refuse les autres).
// Trois zones, comme la maquette Admin-curriculum : liste des référentiels + import ; table
// attendu ↔ compétence (alignement, confiance, état) ; panneau d'édition d'une ligne avec l'aperçu
// « ce que voit l'école » servi par l'API (vocabulaire fermé côté serveur, jamais composé ici).
// Règles rappelées à l'écran : une ligne suggérée n'est pas servie ; publication bloquée tant qu'un
// attendu n'est pas revu.

const ALIGNMENTS: AlignmentType[] = ["EXACT", "PARTIAL", "BROADER", "PREREQ", "ENRICH"];
const CONFIDENCES: MappingConfidence[] = ["H", "M", "L"];
const ALIGN_CHIP: Record<AlignmentType, string> = {
  EXACT: "bg-teal-50 text-teal-700 ring-teal-100",
  PARTIAL: "bg-gold-50 text-gold-700 ring-gold-200",
  BROADER: "bg-sand-100 text-sand-700 ring-sand-300",
  PREREQ: "bg-sand-100 text-sand-600 ring-sand-300",
  ENRICH: "bg-brand-50 text-brand-700 ring-brand-200",
};
const STATE_CHIP: Record<StandardState | "nomatch", string> = {
  reviewed: "bg-teal-50 text-teal-700 ring-teal-100",
  suggested: "bg-gold-50 text-gold-700 ring-gold-200",
  unmapped: "bg-sand-100 text-sand-600 ring-sand-300",
  nomatch: "bg-sand-100 text-sand-500 ring-sand-300",
};
const INPUT = "w-full rounded-lg border border-sand-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400";

type Selection = { standardId: string; competencyId: string | null };
type Draft = {
  competency_id: string;
  alignment_type: AlignmentType;
  confidence: MappingConfidence;
  enrich_kind: "grade" | "requirement" | "";
  note: string;
};

function errText(e: unknown): string {
  return e instanceof ApiError ? e.detail : (e as Error).message;
}

export function CurriculaWorkbench({ frameworkId }: { frameworkId?: string }) {
  const { t, lang } = useLang();
  const router = useRouter();
  const [frameworks, setFrameworks] = useState<CurriculumFrameworkRow[] | null>(null);
  const [detail, setDetail] = useState<CurriculumDetail | null>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [filter, setFilter] = useState<StandardState | "all">("all");
  const [sel, setSel] = useState<Selection | null>(null);

  const name = (fw: { name_en: string; name_ar: string }) => (lang === "ar" ? fw.name_ar : fw.name_en);
  const label = (x: { label_en: string | null; label_ar: string | null }) => (lang === "ar" ? x.label_ar : x.label_en) ?? "";

  const loadList = useCallback(() => {
    api.opsCurricula().then((r) => setFrameworks(r.frameworks)).catch((e) => setError(errText(e)));
  }, []);
  const loadDetail = useCallback(() => {
    if (!frameworkId) {
      setDetail(null);
      return;
    }
    api.opsCurriculum(frameworkId).then(setDetail).catch((e) => setError(errText(e)));
  }, [frameworkId]);

  useEffect(() => {
    loadList();
    api.competencies().then((r) => setNodes(r.nodes)).catch(() => setNodes([]));
  }, [loadList]);
  useEffect(() => {
    setSel(null);
    setNotice(null);
    loadDetail();
  }, [loadDetail]);

  // Après une action sur les lignes, l'API renvoie la couverture : on la pose sans recharger.
  function applyCoverage(cov: FrameworkCoverage) {
    setDetail((d) => (d ? { ...d, coverage: cov } : d));
  }

  async function run<T>(fn: () => Promise<T>, after?: (r: T) => void) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const r = await fn();
      after?.(r);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !frameworks) return <ErrorPanel detail={error} />;
  if (!frameworks) return <Loading label={t("common.loading")} />;

  const cov = detail?.coverage;
  const standards = cov?.standards ?? [];
  const shown = filter === "all" ? standards : standards.filter((s) => s.state === filter);
  const validated = standards.flatMap((s) => s.mappings.filter((m) => !m.suggested));
  const alignCounts = ALIGNMENTS.map((a) => [a, validated.filter((m) => m.alignment_type === a).length] as const).filter(([, n]) => n > 0);
  const selStd = sel ? standards.find((s) => s.id === sel.standardId) ?? null : null;
  const selMap = selStd && sel?.competencyId ? selStd.mappings.find((m) => m.competency_id === sel.competencyId) ?? null : null;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-sand-500">{t("curricula.eyebrow")}</p>
          <h1 className="mt-1 text-2xl font-semibold text-sand-800">{detail ? name(detail) : t("curricula.title")}</h1>
          <p className="mt-1 text-sm text-sand-500">
            {detail && cov ? (
              <>
                <span className="num">
                  {cov.counts.reviewed} {t("curricula.of")} {cov.counts.standards} {t("curricula.reviewed.label")}
                </span>
                {" · "}
                <span className="num">
                  {cov.counts.competencies_mapped} {t("curricula.of")} {cov.counts.competencies_total} {t("curricula.skills.label")}
                </span>
                {" · "}
                {t(detail.status === "published" ? "curricula.status.published" : "curricula.status.draft")}
              </>
            ) : (
              t("curricula.subtitle")
            )}
          </p>
        </div>
        {detail && cov && (
          <div className="flex flex-wrap gap-2">
            {detail.status === "draft" && (
              <Button variant="outline" disabled={busy} onClick={() => run(() => api.opsCurriculumSuggest(detail.id), (r) => {
                setNotice(`${r.suggested} ${t("curricula.suggested.n")}`);
                loadDetail();
              })}>
                {t("curricula.suggest")}
              </Button>
            )}
            {detail.status === "draft" && detail.n_organizations === 0 && (
              <Button variant="ghost" disabled={busy} onClick={() => {
                if (!window.confirm(t("curricula.delete.confirm"))) return;
                run(() => api.opsCurriculumDelete(detail.id), () => router.push("/ops/curricula"));
              }}>
                {t("curricula.delete")}
              </Button>
            )}
            {detail.status === "published" ? (
              <Button variant="outline" disabled={busy} onClick={() => run(() => api.opsCurriculumUnpublish(detail.id), () => {
                setNotice(t("curricula.unpublished"));
                loadList();
                loadDetail();
              })}>
                {t("curricula.unpublish")}
              </Button>
            ) : (
              <Button variant="accent" disabled={busy || !cov.publishable} title={cov.publishable ? undefined : t("curricula.notpublishable")}
                onClick={() => run(() => api.opsCurriculumPublish(detail.id), () => {
                  setNotice(t("curricula.published"));
                  loadList();
                  loadDetail();
                })}>
                {t("curricula.publish")}
              </Button>
            )}
          </div>
        )}
      </header>

      {notice && <p className="rounded-lg bg-teal-50 px-3 py-2 text-sm text-teal-700">{notice}</p>}
      {error && <p className="rounded-lg bg-danger/5 px-3 py-2 text-sm text-danger" dir="auto">{error}</p>}
      {detail && cov && detail.status === "draft" && !cov.publishable && (
        <p className="rounded-lg bg-gold-50 px-3 py-2 text-xs text-gold-700">{t("curricula.notpublishable")}</p>
      )}

      <div className="grid gap-6 lg:grid-cols-12">
        {/* Référentiels + import */}
        <Card className="p-3 lg:col-span-3">
          <p className="px-2 pb-2 text-xs font-semibold uppercase tracking-wide text-sand-500">{t("curricula.list")}</p>
          <ul className="space-y-1">
            {frameworks.map((fw) => (
              <li key={fw.id}>
                <Link
                  href={`/ops/curricula/${fw.id}`}
                  className={cx(
                    "block rounded-lg px-3 py-2 ring-1 transition-colors",
                    fw.id === frameworkId ? "bg-brand-50 ring-brand-200" : "ring-transparent hover:bg-sand-50",
                  )}
                >
                  <span className="block text-sm font-semibold text-sand-800">{name(fw)}</span>
                  <span className="num block text-xs text-sand-500">
                    {t(fw.status === "published" ? "curricula.short.published" : "curricula.short.draft")} · {fw.n_standards}{" "}
                    {t("curricula.standards.label")}
                    {fw.n_organizations > 0 ? ` · ${fw.n_organizations} ${t("curricula.orgs.label")}` : ""}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <button
            onClick={() => setImporting(true)}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-brand-300 px-3 py-2.5 text-sm font-semibold text-brand-700 hover:bg-brand-50"
          >
            <span aria-hidden>+</span> {t("curricula.import")}
          </button>
        </Card>

        {importing ? (
          <div className="lg:col-span-9">
            <ImportForm
              busy={busy}
              onCancel={() => setImporting(false)}
              onSubmit={(body) =>
                run(() => api.opsCurriculaImport(body), (r) => {
                  setImporting(false);
                  setNotice(t("curricula.imported"));
                  loadList();
                  router.push(`/ops/curricula/${r.id}`);
                })
              }
            />
          </div>
        ) : !detail || !cov ? (
          <div className="lg:col-span-9">
            <EmptyState title={t("curricula.title")} body={t("curricula.pick")} />
          </div>
        ) : (
          <>
            {/* Table attendu ↔ compétence */}
            <Card className="p-4 lg:col-span-6">
              <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-sand-600">
                {alignCounts.map(([a, n]) => (
                  <Chip key={a} className={ALIGN_CHIP[a]}>
                    {a} · <span className="num">{n}</span>
                  </Chip>
                ))}
                {cov.counts.suggested > 0 && (
                  <Chip className={STATE_CHIP.suggested}>
                    {t("curricula.state.suggested")} · <span className="num">{cov.counts.suggested}</span>
                  </Chip>
                )}
                <select
                  value={filter}
                  onChange={(e) => setFilter(e.target.value as StandardState | "all")}
                  className="ms-auto rounded-lg border border-sand-300 bg-white px-2 py-1 text-xs"
                  aria-label={t("curricula.col.state")}
                >
                  <option value="all">{t("curricula.filter.all")}</option>
                  <option value="suggested">{t("curricula.state.suggested")}</option>
                  <option value="unmapped">{t("curricula.state.unmapped")}</option>
                  <option value="reviewed">{t("curricula.state.reviewed")}</option>
                </select>
              </div>
              {shown.length === 0 ? (
                <p className="py-8 text-center text-sm text-sand-500">{t("curricula.empty")}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-xs text-sand-500">
                      <tr className="border-b border-sand-100">
                        <th className="py-2 pe-3 text-start font-medium">{t("curricula.col.standard")}</th>
                        <th className="py-2 pe-3 text-start font-medium">{t("curricula.col.skill")}</th>
                        <th className="py-2 pe-3 text-start font-medium">{t("curricula.col.alignment")}</th>
                        <th className="py-2 pe-3 text-start font-medium">{t("curricula.col.confidence")}</th>
                        <th className="py-2 text-start font-medium">{t("curricula.col.state")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.map((st) => (
                        <StandardRows key={st.id} st={st} sel={sel} onSelect={setSel} label={label} t={t} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            {/* Panneau d'édition */}
            <Card className="p-5 lg:col-span-3">
              {!selStd ? (
                <p className="text-sm text-sand-500">{t("curricula.editor.pick")}</p>
              ) : (
                <MappingEditor
                  key={`${selStd.id}:${sel?.competencyId ?? "new"}`}
                  frameworkId={detail.id}
                  published={detail.status === "published"}
                  st={selStd}
                  m={selMap}
                  nodes={nodes}
                  busy={busy}
                  onSaved={(c) => {
                    applyCoverage(c);
                    setNotice(t("curricula.saved"));
                  }}
                  onRemoved={(c) => {
                    applyCoverage(c);
                    setSel({ standardId: selStd.id, competencyId: null });
                  }}
                  run={run}
                />
              )}
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

function StandardRows({
  st, sel, onSelect, label, t,
}: {
  st: CurriculumStandardRow;
  sel: Selection | null;
  onSelect: (s: Selection) => void;
  label: (x: { label_en: string | null; label_ar: string | null }) => string;
  t: (k: DictKey) => string;
}) {
  const stateKey: DictKey = st.no_match ? "curricula.state.nomatch" : (`curricula.state.${st.state}` as DictKey);
  const stateChip = <Chip className={STATE_CHIP[st.no_match ? "nomatch" : st.state]}>{t(stateKey)}</Chip>;
  const stdCell = (
    <td className="py-2 pe-3 align-top">
      <span className="num block font-mono text-xs text-sand-500" data-ltr>
        {st.code}
        {st.grade_hint ? ` · ${st.grade_hint}` : ""}
      </span>
      <span className="block text-sm text-sand-800">{label(st)}</span>
    </td>
  );
  if (st.mappings.length === 0) {
    const active = sel?.standardId === st.id && sel.competencyId === null;
    return (
      <tr
        onClick={() => onSelect({ standardId: st.id, competencyId: null })}
        className={cx("cursor-pointer border-b border-sand-100", active ? "bg-brand-50" : "hover:bg-sand-50")}
      >
        {stdCell}
        <td className="py-2 pe-3 text-sand-400" colSpan={3}>—</td>
        <td className="py-2">{stateChip}</td>
      </tr>
    );
  }
  return (
    <>
      {st.mappings.map((m, i) => {
        const active = sel?.standardId === st.id && sel.competencyId === m.competency_id;
        return (
          <tr
            key={m.competency_id}
            onClick={() => onSelect({ standardId: st.id, competencyId: m.competency_id })}
            className={cx(
              "cursor-pointer",
              i === st.mappings.length - 1 && "border-b border-sand-100",
              active ? "bg-brand-50" : "hover:bg-sand-50",
              m.suggested && "text-sand-500",
            )}
          >
            {i === 0 ? stdCell : <td className="pe-3" />}
            <td className="py-2 pe-3 align-top">
              <span className="block text-sm text-sand-800">{label({ label_en: m.competency_label_en, label_ar: m.competency_label_ar })}</span>
              <span className="num block font-mono text-xs text-sand-400" data-ltr>
                {m.competency_code}
                {m.competency_grade != null ? ` · G${m.competency_grade}` : ""}
              </span>
            </td>
            <td className="py-2 pe-3 align-top">
              <Chip className={cx(ALIGN_CHIP[m.alignment_type], m.suggested && "opacity-70 ring-dashed")}>
                {m.alignment_type}
                {m.enrich_kind ? ` · ${m.enrich_kind}` : ""}
              </Chip>
            </td>
            <td className="num py-2 pe-3 align-top">{m.confidence}</td>
            <td className="py-2 align-top">
              {m.suggested ? <Chip className={STATE_CHIP.suggested}>{t("curricula.state.suggested")}</Chip> : i === 0 ? stateChip : null}
            </td>
          </tr>
        );
      })}
    </>
  );
}

function MappingEditor({
  frameworkId, published, st, m, nodes, busy, onSaved, onRemoved, run,
}: {
  frameworkId: string;
  published: boolean;
  st: CurriculumStandardRow;
  m: CurriculumMappingRow | null;
  nodes: GraphNode[];
  busy: boolean;
  onSaved: (c: FrameworkCoverage) => void;
  onRemoved: (c: FrameworkCoverage) => void;
  run: <T>(fn: () => Promise<T>, after?: (r: T) => void) => Promise<void>;
}) {
  const { t, lang } = useLang();
  const [draft, setDraft] = useState<Draft>({
    competency_id: m?.competency_id ?? "",
    alignment_type: m?.alignment_type ?? "EXACT",
    confidence: m?.confidence ?? "H",
    enrich_kind: m?.enrich_kind ?? "",
    note: m?.note ?? "",
  });
  const [preview, setPreview] = useState<{ preview_en: string; preview_ar: string } | null>(
    m ? { preview_en: m.preview_en, preview_ar: m.preview_ar } : null,
  );
  const [previewErr, setPreviewErr] = useState<string | null>(null);

  // Aperçu « ce que voit l'école » : demandé au serveur à chaque changement (vocabulaire fermé).
  useEffect(() => {
    if (draft.alignment_type === "ENRICH" && !draft.enrich_kind) {
      setPreview(null);
      setPreviewErr(null);
      return;
    }
    const h = setTimeout(() => {
      api
        .opsCurriculumPreview(frameworkId, {
          standard_id: st.id,
          alignment_type: draft.alignment_type,
          confidence: draft.confidence,
          enrich_kind: draft.alignment_type === "ENRICH" ? draft.enrich_kind : null,
        })
        .then((p) => {
          setPreview(p);
          setPreviewErr(null);
        })
        .catch((e) => setPreviewErr(errText(e)));
    }, 150);
    return () => clearTimeout(h);
  }, [frameworkId, st.id, draft.alignment_type, draft.confidence, draft.enrich_kind]);

  const sorted = useMemo(() => [...nodes].sort((a, b) => a.grade - b.grade || a.code.localeCompare(b.code)), [nodes]);
  const canSave = !!draft.competency_id && (draft.alignment_type !== "ENRICH" || !!draft.enrich_kind);
  const hasValidated = st.mappings.some((x) => !x.suggested);

  function save() {
    run(
      () =>
        api.opsCurriculumSetMapping(frameworkId, {
          standard_id: st.id,
          competency_id: draft.competency_id,
          alignment_type: draft.alignment_type,
          confidence: draft.confidence,
          enrich_kind: draft.alignment_type === "ENRICH" ? draft.enrich_kind : null,
          note: draft.note.trim() || null,
        }),
      onSaved,
    );
  }

  return (
    <div className="space-y-4">
      <SectionTitle title={m ? t("curricula.editor.title") : t("curricula.editor.new")} />
      <div>
        <p className="text-xs font-semibold text-sand-500">{t("curricula.editor.standard")}</p>
        <p className="num font-mono text-xs text-sand-500" data-ltr>
          {st.code}
          {st.grade_hint ? ` · ${st.grade_hint}` : ""}
        </p>
        <p className="text-sm font-medium text-sand-800">{st.label_en}</p>
        <p className="font-ar text-sm text-sand-600" dir="rtl">{st.label_ar}</p>
      </div>
      {m?.suggested && <p className="rounded-lg bg-gold-50 px-3 py-2 text-xs text-gold-700">{t("curricula.editor.suggested")}</p>}

      <label className="block">
        <span className="mb-1 block text-xs text-sand-500">{t("curricula.editor.skill")}</span>
        <select value={draft.competency_id} onChange={(e) => setDraft({ ...draft, competency_id: e.target.value })} className={INPUT} disabled={!!m}>
          <option value="">{t("curricula.editor.skill.pick")}</option>
          {sorted.map((n) => (
            <option key={n.id} value={n.id}>
              G{n.grade} · {lang === "ar" ? n.label_ar : n.label_en} ({n.code.replace("MATH.", "")})
            </option>
          ))}
        </select>
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="mb-1 block text-xs text-sand-500">{t("curricula.editor.alignment")}</span>
          <select value={draft.alignment_type} onChange={(e) => setDraft({ ...draft, alignment_type: e.target.value as AlignmentType })} className={INPUT}>
            {ALIGNMENTS.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-sand-500">{t("curricula.editor.confidence")}</span>
          <select value={draft.confidence} onChange={(e) => setDraft({ ...draft, confidence: e.target.value as MappingConfidence })} className={INPUT}>
            {CONFIDENCES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-xs text-sand-500">{t(`curricula.alignment.${draft.alignment_type}` as DictKey)}</p>
      {draft.alignment_type === "ENRICH" && (
        <label className="block">
          <span className="mb-1 block text-xs text-sand-500">{t("curricula.editor.enrich")}</span>
          <select value={draft.enrich_kind} onChange={(e) => setDraft({ ...draft, enrich_kind: e.target.value as Draft["enrich_kind"] })} className={INPUT}>
            <option value="">—</option>
            <option value="grade">{t("curricula.enrich.grade")}</option>
            <option value="requirement">{t("curricula.enrich.requirement")}</option>
          </select>
        </label>
      )}
      <label className="block">
        <span className="mb-1 block text-xs text-sand-500">{t("curricula.editor.note")}</span>
        <input value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} className={INPUT} />
      </label>

      <div className="rounded-xl bg-sand-50 px-3.5 py-3">
        <p className="text-xs font-semibold text-sand-500">{t("curricula.editor.preview")}</p>
        {previewErr ? (
          <p className="mt-1 text-xs text-sand-500" dir="auto">{previewErr}</p>
        ) : preview ? (
          <>
            <p className="mt-1 text-sm text-sand-800" dir="ltr">{preview.preview_en}</p>
            <p className="font-ar mt-0.5 text-sm text-sand-700" dir="rtl">{preview.preview_ar}</p>
          </>
        ) : (
          <p className="mt-1 text-xs text-sand-400">—</p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant="accent" onClick={save} disabled={busy || !canSave}>
          {m?.suggested ? t("curricula.editor.validate") : t("curricula.editor.save")}
        </Button>
        {m && (
          <Button variant="ghost" disabled={busy} onClick={() => run(() => api.opsCurriculumDeleteMapping(frameworkId, st.id, m.competency_id), onRemoved)}>
            {t("curricula.editor.remove")}
          </Button>
        )}
      </div>
      {!published && (
        <div className="border-t border-sand-100 pt-3">
          {st.no_match ? (
            <Button variant="outline" disabled={busy} onClick={() => run(() => api.opsCurriculumNoMatch(frameworkId, st.id, false), onSaved)}>
              {t("curricula.editor.reopen")}
            </Button>
          ) : (
            !hasValidated && (
              <>
                <Button variant="outline" disabled={busy} onClick={() => run(() => api.opsCurriculumNoMatch(frameworkId, st.id, true), onRemoved)}>
                  {t("curricula.editor.nomatch")}
                </Button>
                <p className="mt-1 text-xs text-sand-500">{t("curricula.editor.nomatch.hint")}</p>
              </>
            )
          )}
        </div>
      )}
    </div>
  );
}

function ImportForm({
  busy, onCancel, onSubmit,
}: {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const { t } = useLang();
  const [f, setF] = useState({ key: "", name_en: "", name_ar: "", country: "", source_note: "", csv: "", suggest: true });

  function loadFile(file: File | undefined) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setF((x) => ({ ...x, csv: String(reader.result ?? "") }));
    reader.readAsText(file);
  }

  return (
    <Card className="space-y-4 p-5">
      <SectionTitle title={t("curricula.import.title")} subtitle={t("curricula.import.hint")} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("curricula.import.key")}>
          <input value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} className={INPUT} data-ltr />
        </Field>
        <Field label={t("curricula.import.country")}>
          <input value={f.country} maxLength={2} onChange={(e) => setF({ ...f, country: e.target.value })} className={INPUT} data-ltr />
        </Field>
        <Field label={t("curricula.import.name_en")}>
          <input value={f.name_en} onChange={(e) => setF({ ...f, name_en: e.target.value })} className={INPUT} />
        </Field>
        <Field label={t("curricula.import.name_ar")}>
          <input value={f.name_ar} onChange={(e) => setF({ ...f, name_ar: e.target.value })} className={cx(INPUT, "font-ar")} dir="rtl" />
        </Field>
        <div className="sm:col-span-2">
          <Field label={t("curricula.import.source")}>
            <input value={f.source_note} onChange={(e) => setF({ ...f, source_note: e.target.value })} className={INPUT} />
          </Field>
        </div>
      </div>
      <Field label={t("curricula.import.csv")}>
        <textarea rows={8} value={f.csv} onChange={(e) => setF({ ...f, csv: e.target.value })} className={cx(INPUT, "font-mono text-xs")} dir="ltr"
          placeholder={"code,label_en,label_ar,grade_hint\nY4.F.1,Recognise and show families of equivalent fractions,,Y4"} />
      </Field>
      <label className="flex items-center gap-2 text-sm text-sand-700">
        <span className="text-xs text-sand-500">{t("curricula.import.file")}</span>
        <input type="file" accept=".csv,text/csv" onChange={(e) => loadFile(e.target.files?.[0])} className="text-xs" />
      </label>
      <label className="flex items-center gap-2 text-sm text-sand-700">
        <input type="checkbox" checked={f.suggest} onChange={(e) => setF({ ...f, suggest: e.target.checked })} />
        {t("curricula.import.suggest")}
      </label>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel} disabled={busy}>{t("lessons.cancel")}</Button>
        <Button variant="accent" disabled={busy || !f.key.trim() || !f.name_en.trim() || !f.csv.trim()}
          onClick={() => onSubmit({
            key: f.key.trim(), name_en: f.name_en.trim(), name_ar: f.name_ar.trim() || null, country: f.country.trim() || null,
            source_note: f.source_note.trim() || null, csv: f.csv, suggest: f.suggest,
          })}>
          {t("curricula.import.submit")}
        </Button>
      </div>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-sand-500">{label}</span>
      {children}
    </label>
  );
}
