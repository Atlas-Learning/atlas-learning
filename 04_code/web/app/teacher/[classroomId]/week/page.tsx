"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppShell, useMe } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Button, Card, EmptyState, ErrorPanel, Loading, SectionTitle } from "@/components/ui";
import { GroupCard } from "@/components/GroupCard";
import { api, ApiError } from "@/lib/api";
import type { CheckInInfo, ClassroomProofs, WeeklyPlan } from "@/lib/types";

// E1 · Cette semaine (B5) — maquette Main.dc.html. Une action principale : lancer un check-in.
export default function WeekPage({ params }: { params: { classroomId: string } }) {
  return (
    <AppShell>
      <WeekView classroomId={params.classroomId} />
    </AppShell>
  );
}

function WeekView({ classroomId }: { classroomId: string }) {
  const { t, lang } = useLang();
  const me = useMe();
  const router = useRouter();
  const isTeacher = me?.roles.includes("teacher") && me.classrooms.some((c) => c.id === classroomId);
  const [plan, setPlan] = useState<WeeklyPlan | null | undefined>(undefined);
  const [proofs, setProofs] = useState<ClassroomProofs | null>(null);
  const [checkins, setCheckins] = useState<CheckInInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.classroomPlan(classroomId).then(setPlan).catch((e) => {
      if (e instanceof ApiError && e.status === 404) setPlan(null);
      else setError(e instanceof ApiError ? e.detail : (e as Error).message);
    });
    api.classroomProofs(classroomId).then(setProofs).catch(() => setProofs(null));
    api.classroomCheckins(classroomId).then((r) => setCheckins(r.checkins)).catch(() => setCheckins([]));
  }, [classroomId]);

  useEffect(() => {
    load();
  }, [load]);

  async function launch() {
    setBusy(true);
    try {
      const ci = await api.openCheckin(classroomId, { kind: "full" });
      router.push(`/teacher/${classroomId}/checkin/${ci.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message);
      setBusy(false);
    }
  }

  if (error) return <ErrorPanel detail={error} />;
  if (plan === undefined) return <Loading label={t("common.loading")} />;

  const open = checkins.find((c) => c.status === "open");
  const scheduled = checkins.filter((c) => c.status === "scheduled");
  const last = proofs?.proofs[0];
  const className = me?.classrooms.find((c) => c.id === classroomId)?.name;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-brand-600">{className}</p>
          <h1 className="mt-0.5 text-2xl font-semibold text-sand-800">{t("week.title")}</h1>
          <p className="mt-1 text-sm text-sand-500">
            {plan ? `${t("week.of")} ${plan.week_start} · ` : ""}{t("week.subtitle")}
          </p>
        </div>
        {isTeacher && (
          <div className="text-end">
            {open ? (
              <Button variant="accent" onClick={() => router.push(`/teacher/${classroomId}/checkin/${open.id}`)}>
                {t("week.recheck.resume")} · {open.kind === "full" ? t("checkin.full") : t("checkin.targeted")}
              </Button>
            ) : (
              <Button variant="accent" onClick={launch} disabled={busy}>{t("week.checkin")}</Button>
            )}
            <p className="mt-1 text-xs text-sand-400">{t("week.checkin.hint")}</p>
          </div>
        )}
      </header>

      {/* Compteur de boucles bouclées : enseignant seul. */}
      {isTeacher && proofs && (
        <div className="flex flex-wrap items-center gap-6 rounded-2xl border border-sand-200 bg-white px-5 py-3">
          <div>
            <span className="num text-2xl font-semibold text-brand-700">{proofs.loops_closed}</span>
            <span className="ms-2 text-sm text-sand-600">{t("week.loops")}</span>
          </div>
          <p className="text-xs text-sand-400">{t("week.loops.hint")}</p>
        </div>
      )}

      {/* Re-checks planifiés : à démarrer. */}
      {isTeacher && scheduled.length > 0 && (
        <Card className="p-4">
          <SectionTitle title={t("week.recheck.scheduled")} />
          <ul className="space-y-2">
            {scheduled.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-sand-700">{t("checkin.targeted")} · <span className="num">{c.n_members}</span> {t("week.action.members")}</span>
                <Button variant="outline" onClick={async () => {
                  await api.startCheckin(c.id);
                  router.push(`/teacher/${classroomId}/checkin/${c.id}`);
                }}>{t("week.recheck.start")}</Button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Bandeau dernière preuve. */}
      {last && last.computed && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-gold-50 px-5 py-3 ring-1 ring-gold-200">
          <p className="text-sm text-gold-800">
            <span className="font-semibold">{t("week.lastproof")}</span> · {lang === "ar" ? last.root_cause?.label_ar : last.root_cause?.label_en} ·{" "}
            <span className="num font-semibold">{last.header.unlocked}</span> {t("week.lastproof.of")} <span className="num">{last.header.rechecked}</span> {t("week.lastproof.unlocked")}
          </p>
          <Link href={`/teacher/${classroomId}/actions/${last.action_id}/proof`} className="text-sm font-medium text-gold-800 underline">
            {t("week.lastproof.open")}
          </Link>
        </div>
      )}

      {!plan ? (
        <EmptyState title={t("week.empty.title")} body={t("week.empty.body")} />
      ) : (
        <ul className="space-y-3">
          {plan.actions.map((a) => <GroupCard key={a.id} action={a} classroomId={classroomId} />)}
        </ul>
      )}
    </div>
  );
}
