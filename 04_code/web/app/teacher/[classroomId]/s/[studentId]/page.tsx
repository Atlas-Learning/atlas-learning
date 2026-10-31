"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Card, EmptyState, ErrorPanel, Loading, SectionTitle, cx } from "@/components/ui";
import { CompetencyCard } from "@/components/Mastery";
import { DiagnosisBlock } from "@/components/DiagnosisBlock";
import { TutorExplain } from "@/components/TutorExplain";
import { RestitutionCard } from "@/components/RestitutionCard";
import { RemediationModal } from "@/components/RemediationModal";
import { api, type Guardian } from "@/lib/api";
import type { StudentProfile, UnlockHistory } from "@/lib/types";
import { CausalThread } from "@/components/CausalThread";

export default function StudentProfilePage({
  params,
}: {
  params: { classroomId: string; studentId: string };
}) {
  return (
    <AppShell>
      <ProfileView classroomId={params.classroomId} studentId={params.studentId} />
    </AppShell>
  );
}

function ProfileView({ classroomId, studentId }: { classroomId: string; studentId: string }) {
  const { t, lang, dir } = useLang();
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [remediate, setRemediate] = useState<string | null>(null);
  const [unlocks, setUnlocks] = useState<UnlockHistory | null>(null);

  useEffect(() => {
    api.studentProfile(studentId).then(setProfile).catch((e) => setError(e.message));
    api.studentUnlocks(studentId).then(setUnlocks).catch(() => setUnlocks(null));
  }, [studentId]);

  if (error) return <ErrorPanel detail={error} />;
  if (!profile) return <Loading label={t("common.loading")} />;

  const primary = profile.diagnoses.find((d) => !d.is_self) ?? profile.diagnoses[0];
  const others = profile.diagnoses.filter((d) => d !== primary);
  const enoughData = profile.n_measured >= 3;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={`/teacher/${classroomId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:underline"
        >
          <svg className="rtl-flip" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 6l-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t("common.back")}
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-sand-800">
          {t("common.student")} <span className="num text-brand-700">{profile.external_ref}</span>
        </h1>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Restitution. */}
        <div className="lg:col-span-1">
          <RestitutionCard r={profile.restitution} />
          <p className="mt-3 px-1 text-xs text-sand-500">
            {profile.n_measured} {t("common.skills")} {t("common.measured").toLowerCase()} ·{" "}
            <span className="num">{profile.n_gaps}</span> {t("common.gaps")}
          </p>
        </div>

        {/* Diagnostic causal — l'écran héros. */}
        <Card className="p-5 lg:col-span-2">
          <SectionTitle title={t("profile.diagnosis.title")} subtitle={t("profile.diagnosis.subtitle")} />
          {primary && (
            <div className="mb-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-sand-400">{t("thread.title")}</p>
              <CausalThread
                mastered={(() => { const m = profile.competencies.filter((c) => c.mastered).sort((a, b) => b.ability_elo - a.ability_elo)[0]; return m ? (lang === "ar" ? m.label_ar : m.label_en) : null; })()}
                root={lang === "ar" ? primary.root_cause_label_ar : primary.root_cause_label}
                shows={primary.is_self ? null : (lang === "ar" ? primary.gap_label_ar : primary.gap_label)}
              />
            </div>
          )}
          {!primary ? (
            <div className="rounded-2xl bg-emerald-50 p-6 text-center">
              <p className="text-lg font-semibold text-emerald-800">{t("profile.nogaps.title")}</p>
              <p className="mt-1 text-sm text-emerald-700">{t("profile.nogaps.body")}</p>
            </div>
          ) : (
            <>
              <DiagnosisBlock d={primary} onRemediate={(code) => setRemediate(code)} />
              {/* Le moteur « parle » : pourquoi cet exercice, sur la lacune analysée. */}
              <TutorExplain studentId={studentId} gapCode={primary.gap} />
              {others.length > 0 && (
                <div className="mt-5">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-sand-400">
                    {t("profile.othergaps")}
                  </p>
                  <ul className="space-y-1.5">
                    {others.slice(0, 5).map((d) => (
                      <li
                        key={d.gap}
                        className="flex items-center justify-between gap-3 rounded-lg bg-sand-50 px-3 py-2 text-sm"
                      >
                        <span className="text-sand-700">{lang === "ar" ? d.gap_label_ar : d.gap_label}</span>
                        <button
                          onClick={() => setRemediate(d.root_cause)}
                          className="shrink-0 text-xs font-medium text-brand-600 hover:underline"
                        >
                          {t("common.next.step")} →
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </Card>
      </div>

      {/* Profil de maîtrise. */}
      <Card className="p-5">
        <SectionTitle title={t("profile.mastery.title")} subtitle={t("profile.mastery.subtitle")} />
        {!enoughData ? (
          <EmptyState title={t("empty.student.title")} body={t("empty.student.body")} />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {profile.competencies.map((c) => (
              <CompetencyCard key={c.code} c={c} />
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <SectionTitle title={t("unlocks.title")} />
          {!unlocks || unlocks.unlocks.length === 0 ? (
            <p className="text-sm text-sand-400">{t("unlocks.none")}</p>
          ) : (
            <ul className="space-y-2">
              {unlocks.unlocks.map((u, i) => (
                <li key={i} className="flex items-center justify-between rounded-xl bg-gold-50 px-3 py-2 text-sm ring-1 ring-gold-200">
                  <span className="font-medium text-gold-800">{lang === "ar" ? u.label_ar : u.label_en}</span>
                  <span className="num text-xs text-gold-700">{u.unlocked_at?.slice(0, 10)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="p-5">
          <SectionTitle title={t("family.preview")} />
          <p className="text-sm text-sand-500">{t("family.preview.body")}</p>
        </Card>
      </div>

      <GuardiansSection studentId={studentId} />

      {remediate && (
        <div dir={dir}>
          <RemediationModal competencyCode={remediate} onClose={() => setRemediate(null)} />
        </div>
      )}
    </div>
  );
}

function GuardiansSection({ studentId }: { studentId: string }) {
  const { t } = useLang();
  const [guardians, setGuardians] = useState<Guardian[]>([]);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setGuardians((await api.listGuardians(studentId)).guardians);
    } catch {
      setGuardians([]);
    }
  }
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studentId]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!email) return;
    setBusy(true);
    try {
      await api.addGuardian(studentId, email);
      setEmail("");
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function remove(userId: string) {
    await api.removeGuardian(studentId, userId);
    await load();
  }

  return (
    <Card className="p-5">
      <SectionTitle title={t("guardians.title")} />
      <p className="mb-3 text-xs text-sand-500">{t("guardians.hint")}</p>
      {guardians.length > 0 && (
        <ul className="mb-4 divide-y divide-sand-50 text-sm">
          {guardians.map((g) => (
            <li key={g.user_id} className="flex items-center justify-between gap-3 py-2">
              <span className="text-sand-700" data-ltr>
                {g.email}
                <span className="ms-2 rounded bg-sand-100 px-1.5 py-0.5 text-xs text-sand-500">
                  {t(g.source === "staff" ? "guardians.staff" : "guardians.roster")}
                </span>
              </span>
              <button onClick={() => remove(g.user_id)} className="text-xs text-danger hover:underline">
                {t("guardians.remove")}
              </button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={add} className="flex gap-2">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t("guardians.placeholder")}
          className="flex-1 rounded-lg border border-sand-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400"
          autoComplete="off"
          data-ltr
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {t("guardians.add")}
        </button>
      </form>
    </Card>
  );
}
