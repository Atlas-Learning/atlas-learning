"use client";

import { useEffect, useState } from "react";
import { AppShell, useMe } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Button, Card, Chip, Loading, SectionTitle, cx } from "@/components/ui";
import { EthicsStance } from "@/components/EthicsStance";
import { api, type AuditEntry, type Integration, type RosterRun, type SetupState } from "@/lib/api";
import type { CurriculumSettings, SchoolMailSettings } from "@/lib/types";
import type { DictKey } from "@/lib/i18n";

const STEP_LABEL: Record<string, DictKey> = {
  connect: "it.step.connect",
  sync: "it.step.sync",
  verify: "it.step.verify",
  parents: "it.step.parents",
};

/**
 * Console IT (écran J) : intégration d'annuaire Google + rostering.
 * Gate d'achat : l'IT admin connecte son domaine, déclenche/suit les synchronisations.
 */
export default function ITPage() {
  return (
    <AppShell narrow>
      <ITView />
    </AppShell>
  );
}

const STATUS_STYLE: Record<string, string> = {
  connected: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  pending: "bg-amber-50 text-amber-800 ring-amber-200",
  error: "bg-rose-50 text-rose-800 ring-rose-200",
  over_capacity: "bg-rose-50 text-rose-800 ring-rose-200",
  blocked: "bg-amber-50 text-amber-800 ring-amber-200",
};

const STATUS_KEY: Record<string, DictKey> = {
  pending: "it.status.pending",
  connected: "it.status.connected",
  error: "it.status.error",
  over_capacity: "it.status.over",
  blocked: "it.status.blocked",
};

// Libellés des frameworks : noms servis par la table (refonte C1), repli sur les clés
// historiques traduites pour les anciens payloads.
const FRAMEWORK_KEY: Record<string, DictKey> = {
  ATLAS: "curriculum.fw.atlas",
  CCSS_M: "curriculum.fw.ccssm",
  UK_NC: "curriculum.fw.uknc",
  MOE_UAE: "curriculum.fw.moe",
};

function frameworkName(cur: CurriculumSettings, key: string, lang: string, t: (k: DictKey) => string): string {
  const fw = cur.frameworks?.find((f) => f.key === key);
  if (fw) return lang === "ar" ? fw.name_ar : fw.name_en;
  return FRAMEWORK_KEY[key] ? t(FRAMEWORK_KEY[key]) : key;
}

function ITView() {
  const { t, lang } = useLang();
  const me = useMe();
  // Q14 : le framework affiché se règle côté Atlas ; l'école le lit sans le modifier.
  const canSetCurriculum = me?.roles.includes("super_admin") ?? false;
  const [data, setData] = useState<Integration | null>(null);
  const [runs, setRuns] = useState<RosterRun[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [setup, setSetup] = useState<SetupState | null>(null);
  const [curriculum, setCurriculum] = useState<CurriculumSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [curError, setCurError] = useState<string | null>(null);

  async function refresh() {
    const [integ, history, log, st, cur] = await Promise.all([
      api.adminIntegration(), api.rosteringRuns(), api.adminAudit(), api.adminSetup(),
      api.adminCurriculum(),
    ]);
    setData(integ);
    setRuns(history.runs);
    setAudit(log.entries);
    setSetup(st);
    setCurriculum(cur);
  }

  async function setCurriculumView(view: string) {
    setBusy(true);
    setCurError(null);
    try {
      await api.adminSetCurriculum(view);
      setCurriculum(await api.adminCurriculum());
    } catch {
      setCurError(t("curriculum.error"));
    } finally {
      setBusy(false);
    }
  }

  async function inviteParents() {
    setBusy(true);
    try {
      await api.parentsInvite();
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function exportData() {
    const bundle = await api.adminExport();
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `atlas-export-${data?.organization.domain ?? "tenant"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  useEffect(() => {
    refresh().catch(() => setError(t("it.loaderror"))).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function sync(force = false) {
    setBusy(true);
    setError(null);
    try {
      await api.rosteringSync(force);
      await refresh();
    } catch {
      setError(t("it.syncerror"));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading label={t("common.loading")} />;

  const fmt = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString(lang === "ar" ? "ar" : "en-GB") : t("it.never");
  const status = data?.integration?.status ?? "pending";

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-sand-800">{t("it.title")}</h1>
        <p className="mt-1 text-sm text-sand-500">{t("it.subtitle")}</p>
      </header>

      {/* Parti pris éthique affiché = argument de gouvernance IA face au régulateur (Mouvement 04). */}
      <EthicsStance variant="governance" />

      {/* Mise en route guidée — tant que tout n'est pas coché */}
      {setup && setup.done < setup.total && (
        <Card className="p-5">
          <SectionTitle title={`${t("it.setup")} (${setup.done}/${setup.total})`} />
          <ul className="mt-2 space-y-2">
            {setup.steps.map((step) => (
              <li key={step.key} className="flex items-center gap-3 text-sm">
                <span
                  className={`grid h-5 w-5 shrink-0 place-items-center rounded-full text-xs ${
                    step.done ? "bg-emerald-500 text-white" : "bg-sand-200 text-sand-500"
                  }`}
                >
                  {step.done ? "✓" : ""}
                </span>
                <span className={step.done ? "text-sand-400 line-through" : "text-sand-700"}>
                  {t(STEP_LABEL[step.key] ?? "it.setup")}
                </span>
                {step.key === "parents" && !step.done && (
                  <button
                    onClick={inviteParents}
                    disabled={busy}
                    className="ms-auto text-xs font-medium text-brand-600 hover:underline"
                  >
                    {t("it.invite")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Intégration d'annuaire */}
      <Card className="p-5">
        <div className="mb-4 flex items-center justify-between gap-4">
          <SectionTitle title={t("it.rostering")} />
          <Chip className={`shrink-0 ${STATUS_STYLE[status] ?? STATUS_STYLE.pending}`}>
            {t(STATUS_KEY[status] ?? "it.status.pending")}
          </Chip>
        </div>

        <dl className="grid grid-cols-2 gap-4 text-sm">
          <Info label={t("it.domain")} value={data?.organization.domain ?? "—"} />
          <Info label={t("it.lastsync")} value={fmt(data?.integration?.last_sync_at ?? null)} />
          <div>
            <dt className="text-xs text-sand-400">{t("it.seats")}</dt>
            <dd
              className={`mt-0.5 font-medium ${data?.organization.over_capacity ? "text-rose-600" : "text-sand-800"}`}
              data-ltr
            >
              {data?.organization.seats != null
                ? `${data.organization.seats_used} / ${data.organization.seats}`
                : String(data?.organization.seats_used ?? 0)}
              {data?.organization.over_capacity ? ` · ${t("it.overcap")}` : ""}
            </dd>
          </div>
          <Info label={t("it.admin")} value={data?.integration?.admin_email ?? "—"} />
        </dl>

        {data?.integration?.last_error && (
          <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700" data-ltr>
            {data.integration.last_error}
          </p>
        )}
        {error && <p className="mt-3 text-sm text-danger">{error}</p>}

        {status === "blocked" && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
            <p className="text-sm font-medium text-amber-900">
              {t("it.blocked.title")}
            </p>
            <p className="mt-1 text-sm text-amber-800">
              {t("it.blocked.body").replace(
                "{n}",
                String(runs.find((r) => r.status === "blocked")?.pending_deactivations ?? "?"),
              )}
            </p>
            <Button
              onClick={() => sync(true)}
              disabled={busy}
              className="mt-3 bg-rose-600 text-white hover:bg-rose-700"
            >
              {t("it.blocked.approve")}
            </Button>
          </div>
        )}

        <div className="mt-5">
          <Button onClick={() => sync(false)} disabled={busy}>
            {busy ? t("it.syncing") : t("it.sync")}
          </Button>
        </div>
      </Card>

      {/* Vue curriculaire (B3) : framework d'affichage du tenant — un seul actif en v1 (D-B3). */}
      {curriculum && (
        <Card className="p-5">
          <div className="mb-1 flex items-center justify-between gap-4">
            <SectionTitle title={t("curriculum.title")} />
            <Chip className="shrink-0 bg-brand-50 text-brand-700 ring-brand-200">
              {t("curriculum.current")} · {frameworkName(curriculum, curriculum.curriculum_view, lang, t)}
            </Chip>
          </div>
          <p className="mb-3 text-xs text-sand-500">
            {canSetCurriculum ? t("curriculum.hint") : t("curriculum.readonly")}
          </p>
          {/* Refonte C3 : un framework choisi mais encore en brouillon chez Atlas n'est pas servi. */}
          {curriculum.configured_view && curriculum.configured_view !== curriculum.curriculum_view && (
            <p className="mb-3 rounded-lg bg-gold-50 px-3 py-2 text-xs text-gold-700">
              {t("curriculum.configured.draft")} <span className="font-medium" data-ltr>({curriculum.configured_view})</span>
            </p>
          )}
          <label className="block text-xs text-sand-400" htmlFor="curriculum-view">
            {t("curriculum.select")}
          </label>
          <select
            id="curriculum-view"
            value={curriculum.curriculum_view}
            onChange={(e) => setCurriculumView(e.target.value)}
            disabled={busy || !canSetCurriculum}
            className="mt-1 w-full max-w-xs rounded-lg border border-sand-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400 disabled:opacity-50 sm:w-auto"
          >
            {curriculum.available_frameworks.map((fw) => (
              <option key={fw} value={fw}>
                {frameworkName(curriculum, fw, lang, t)}
              </option>
            ))}
          </select>
          {curError && <p className="mt-3 text-sm text-danger">{curError}</p>}
        </Card>
      )}

      {/* B6 / I1 : message hebdomadaire « votre plan est prêt », réglé par école. */}
      <WeeklyMailSettings />

      {/* Historique des synchronisations */}
      <Card className="p-5">
        <SectionTitle title={t("it.runs")} />
        {runs.length === 0 ? (
          <p className="py-4 text-sm text-sand-500">{t("it.noruns")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-sand-400">
              <tr className="border-b border-sand-100 text-start">
                <th className="py-2 text-start font-medium">{t("it.col.date")}</th>
                <th className="py-2 text-end font-medium">{t("it.col.created")}</th>
                <th className="py-2 text-end font-medium">{t("it.col.updated")}</th>
                <th className="py-2 text-end font-medium">{t("it.col.deactivated")}</th>
                <th className="py-2 text-end font-medium">{t("it.col.errors")}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-b border-sand-50 last:border-0">
                  <td className="py-2 text-sand-700">{fmt(r.started_at)}</td>
                  <td className="py-2 text-end text-sand-700">{r.created}</td>
                  <td className="py-2 text-end text-sand-700">{r.updated}</td>
                  <td className="py-2 text-end text-sand-700">{r.deactivated}</td>
                  <td className={`py-2 text-end ${r.errors ? "text-rose-600" : "text-sand-400"}`}>
                    {r.errors}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Conformité PDPL : audit visible + portabilité */}
      <Card className="p-5">
        <div className="mb-3 flex items-center justify-between gap-4">
          <SectionTitle title={t("it.compliance")} />
          <Button onClick={exportData} className="bg-sand-100 text-sand-700 hover:bg-sand-200">
            {t("it.export")}
          </Button>
        </div>
        {audit.length === 0 ? (
          <p className="py-2 text-sm text-sand-500">{t("it.noaudit")}</p>
        ) : (
          <ul className="divide-y divide-sand-50 text-sm">
            {audit.map((e) => (
              <li key={e.id} className="flex items-center justify-between gap-4 py-2">
                <span className="font-medium text-sand-700" data-ltr>{e.action}</span>
                <span className="shrink-0 text-xs text-sand-400">{fmt(e.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Posture sécurité (rappel) */}
      <Card className="p-5">
        <SectionTitle title={t("it.security")} />
        <ul className="mt-1 grid gap-2 text-sm text-sand-600 sm:grid-cols-2">
          <li>• {lang === "ar" ? "MFA إلزامي للطاقم (TOTP)" : "MFA staff obligatoire (TOTP)"}</li>
          <li>• {lang === "ar" ? "SSO OIDC (Google / Microsoft)" : "SSO OIDC (Google / Microsoft)"}</li>
          <li>• {lang === "ar" ? "إقامة البيانات في الإمارات" : "Résidence des données UAE"}</li>
          <li>• {lang === "ar" ? "سجل تدقيق غير قابل للتعديل" : "Journal d'audit append-only"}</li>
        </ul>
      </Card>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-sand-400">{label}</dt>
      <dd className="mt-0.5 font-medium text-sand-800" data-ltr>{value}</dd>
    </div>
  );
}


function WeeklyMailSettings() {
  const { t } = useLang();
  const [schools, setSchools] = useState<SchoolMailSettings[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Partial<SchoolMailSettings>>>({});
  const [state, setState] = useState<Record<string, "saving" | "saved" | "error" | undefined>>({});

  useEffect(() => {
    api.adminSchools().then((r) => setSchools(r.schools)).catch(() => setSchools([]));
  }, []);

  if (!schools || schools.length === 0) return null;

  const get = (s: SchoolMailSettings, k: "country" | "plan_mail_weekday" | "plan_mail_hour" | "timezone") =>
    k in (drafts[s.id] ?? {}) ? (drafts[s.id] as Record<string, unknown>)[k] : s[k];
  const set = (id: string, k: string, v: unknown) => setDrafts((d) => ({ ...d, [id]: { ...(d[id] ?? {}), [k]: v } }));

  async function save(s: SchoolMailSettings) {
    const d = drafts[s.id];
    if (!d) return;
    setState((x) => ({ ...x, [s.id]: "saving" }));
    try {
      const r = await api.schoolSettingsPatch(s.id, d as Record<string, never>);
      setSchools((all) => (all ?? []).map((x) => (x.id === s.id ? { ...x, ...r, id: s.id, name: s.name } : x)));
      setDrafts((x) => { const n = { ...x }; delete n[s.id]; return n; });
      setState((x) => ({ ...x, [s.id]: "saved" }));
    } catch {
      setState((x) => ({ ...x, [s.id]: "error" }));
    }
  }

  const SELECT = "mt-1 w-full rounded-lg border border-sand-300 bg-white px-2 py-1.5 text-sm outline-none focus:border-brand-400";
  return (
    <Card className="p-5">
      <SectionTitle title={t("mail.title")} />
      <p className="mb-3 text-xs text-sand-500">{t("mail.subtitle")}</p>
      <ul className="space-y-4">
        {schools.map((s) => (
          <li key={s.id} className="rounded-xl border border-sand-200 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium text-sand-800">{s.name}</p>
              <p className="num text-xs text-sand-500">
                {t("mail.effective")}: {t(`mail.day.${s.effective.weekday}` as DictKey)} · {String(s.effective.hour).padStart(2, "0")}:00 · {s.effective.timezone}
              </p>
            </div>
            <div className="mt-2 grid gap-2 sm:grid-cols-4">
              <label className="text-xs text-sand-500">{t("mail.country")}
                <input value={(get(s, "country") as string | null) ?? ""} maxLength={2} placeholder="AE"
                  onChange={(e) => set(s.id, "country", e.target.value.toUpperCase() || null)} className={cx(SELECT, "num uppercase")} data-ltr />
              </label>
              <label className="text-xs text-sand-500">{t("mail.weekday")}
                <select value={(get(s, "plan_mail_weekday") as number | null) ?? ""} className={SELECT}
                  onChange={(e) => set(s.id, "plan_mail_weekday", e.target.value === "" ? null : Number(e.target.value))}>
                  <option value="">{t("mail.default")}</option>
                  {[0, 1, 2, 3, 4, 5, 6].map((d) => <option key={d} value={d}>{t(`mail.day.${d}` as DictKey)}</option>)}
                </select>
              </label>
              <label className="text-xs text-sand-500">{t("mail.hour")}
                <select value={(get(s, "plan_mail_hour") as number | null) ?? ""} className={cx(SELECT, "num")}
                  onChange={(e) => set(s.id, "plan_mail_hour", e.target.value === "" ? null : Number(e.target.value))}>
                  <option value="">{t("mail.default")}</option>
                  {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
                </select>
              </label>
              <label className="text-xs text-sand-500">{t("mail.timezone")}
                <input value={(get(s, "timezone") as string | null) ?? ""} placeholder={s.effective.timezone}
                  onChange={(e) => set(s.id, "timezone", e.target.value || null)} className={SELECT} data-ltr />
              </label>
            </div>
            <div className="mt-2 flex items-center justify-end gap-2 text-xs">
              {state[s.id] === "saved" && <span className="text-teal-700">{t("mail.saved")}</span>}
              {state[s.id] === "error" && <span className="text-danger">{t("mail.error")}</span>}
              <Button variant="outline" disabled={!drafts[s.id] || state[s.id] === "saving"} onClick={() => save(s)}>{t("mail.save")}</Button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
