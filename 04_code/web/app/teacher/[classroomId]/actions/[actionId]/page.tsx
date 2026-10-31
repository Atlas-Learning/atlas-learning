"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppShell, useMe } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Button, Card, Chip, ErrorPanel, Loading, SectionTitle, cx } from "@/components/ui";
import { CausalThread } from "@/components/CausalThread";
import { MasteryRange, StateDot } from "@/components/MasteryRange";
import { api, ApiError } from "@/lib/api";
import type { Lesson, PlanAction, StudentRow } from "@/lib/types";
import type { DictKey } from "@/lib/i18n";

// E3 · Groupe et mini-leçon (B5) — maquette Group.dc.html.
export default function ActionPage({ params }: { params: { classroomId: string; actionId: string } }) {
  return (
    <AppShell>
      <ActionView classroomId={params.classroomId} actionId={params.actionId} />
    </AppShell>
  );
}

function ActionView({ classroomId, actionId }: { classroomId: string; actionId: string }) {
  const { t, lang } = useLang();
  const me = useMe();
  const router = useRouter();
  const isTeacher = me?.roles.includes("teacher") && me.classrooms.some((c) => c.id === classroomId);
  const [action, setAction] = useState<PlanAction | null>(null);
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [students, setStudents] = useState<StudentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [projecting, setProjecting] = useState(false);

  const load = useCallback(() => {
    api.planAction(actionId).then((a) => {
      setAction(a);
      if (a.lesson_id) api.lesson(a.lesson_id).then(setLesson).catch(() => setLesson(null));
    }).catch((e) => setError(e instanceof ApiError ? e.detail : (e as Error).message));
    api.classStudents(classroomId).then((r) => setStudents(r.students)).catch(() => undefined);
  }, [actionId, classroomId]);

  useEffect(() => { load(); }, [load]);

  if (error) return <ErrorPanel detail={error} />;
  if (!action) return <Loading label={t("common.loading")} />;

  const label = (c: { label_en: string; label_ar: string }) => (lang === "ar" ? c.label_ar : c.label_en);
  const members = action.members ?? [];
  const active = members.filter((m) => !m.removed_by_teacher);
  const inGroup = new Set(members.map((m) => m.student_id));
  const candidates = students.filter((s) => !inGroup.has(s.student_id));
  const useAr = lang === "ar" && lesson?.arabic_complete && lesson.status !== "draft";

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try { await fn(); load(); } catch (e) { setError(e instanceof ApiError ? e.detail : (e as Error).message); } finally { setBusy(null); }
  };

  async function taught() {
    setBusy("taught");
    try {
      const r = await api.planActionDone(action!.id);
      router.push(`/teacher/${classroomId}/checkin/${r.recheck.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message);
      setBusy(null);
    }
  }

  return (
    <div className={cx("space-y-6", projecting && "projection")}>
      <div className="print:hidden">
        <Link href={`/teacher/${classroomId}/week`} className="text-sm font-medium text-brand-600 hover:underline">← {t("week.title")}</Link>
      </div>
      <header>
        <h1 className="text-2xl font-semibold text-sand-800">{t("action.title")}</h1>
        <div className="mt-3"><CausalThread mastered={null} root={label(action.root_cause)} shows={label(action.blocked)} /></div>
        <p className="mt-3 text-sand-700" dir="auto">{lang === "ar" ? action.because_ar : action.because_en}</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Groupe. */}
        <Card className="p-5 lg:col-span-2 print:hidden">
          <SectionTitle title={`${t("group.members")} · ${active.length}`} />
          <ul className="divide-y divide-sand-100">
            {members.map((m) => (
              <li key={m.student_id} className={cx("flex items-start justify-between gap-3 py-2.5", m.removed_by_teacher && "opacity-50")}>
                <div className="min-w-0">
                  <p className="num text-sm font-medium text-sand-800">
                    {m.external_ref ?? "—"}
                    {m.source === "teacher_added" && <span className="ms-2 text-xs font-normal text-sand-400">{t("group.added")}</span>}
                    {m.removed_by_teacher && <span className="ms-2 text-xs font-normal text-sand-400">{t("group.removed")}</span>}
                  </p>
                  <div className="mt-1 flex items-center gap-2 text-xs text-sand-500">
                    <StateDot state={m.root.state} /> {t("group.root.state")} · {t(`matrix.legend.${m.root.state}` as DictKey)}
                  </div>
                  <div className="mt-1 w-40"><MasteryRange elo={m.root.elo} state={m.root.state} estimated={m.root.state === "estimated"} compact /></div>
                  {m.observed_error && <p className="num mt-1 text-xs text-gold-700" dir="ltr">{t("group.observed")}: {m.observed_error}</p>}
                </div>
                {isTeacher && action.status === "proposed" && (
                  <Button variant="ghost" disabled={busy !== null}
                    onClick={() => run("m", () => m.removed_by_teacher
                      ? api.planActionMembers(action.id, [m.student_id], [])
                      : api.planActionMembers(action.id, [], [m.student_id]))}>
                    {m.removed_by_teacher ? t("group.restore") : t("group.remove")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
          {isTeacher && action.status === "proposed" && (
            adding ? (
              <select className="mt-3 w-full rounded-lg border border-sand-300 bg-white px-3 py-2 text-sm" defaultValue=""
                onChange={(e) => { if (e.target.value) run("add", () => api.planActionMembers(action.id, [e.target.value], [])); setAdding(false); }}>
                <option value="">{t("group.add")}…</option>
                {candidates.map((s) => <option key={s.student_id} value={s.student_id}>{s.external_ref}</option>)}
              </select>
            ) : (
              <Button variant="outline" className="mt-3" onClick={() => setAdding(true)} disabled={candidates.length === 0}>{t("group.add")}</Button>
            )
          )}
        </Card>

        {/* Mini-leçon. */}
        <Card className="p-5 lg:col-span-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <SectionTitle title={lesson ? (useAr ? lesson.title_ar ?? lesson.title_en : lesson.title_en) : t("week.action.nolesson")}
              subtitle={lesson ? `${lesson.duration_min} ${t("group.lesson.min")} · ${t("group.lesson.status")}: ${lesson.status}` : undefined} />
            {lesson && (
              <div className="flex gap-2 print:hidden">
                <Button variant="outline" onClick={() => setProjecting((p) => !p)}>{projecting ? t("checkin.exit") : t("group.lesson.project")}</Button>
                <Button variant="outline" onClick={() => window.print()}>{t("group.lesson.print")}</Button>
              </div>
            )}
          </div>
          {lesson && lang === "ar" && !useAr && <p className="mb-3 text-xs text-sand-500">{t("group.lesson.noar")}</p>}
          {lesson && (
            <ol className={cx("space-y-3", projecting && "text-lg")}>
              {lesson.steps.map((st, i) => (
                <li key={i} className="rounded-xl border border-sand-200 p-4">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">{t(`group.step.${st.kind}` as DictKey)}</p>
                    <span className="num text-xs text-sand-400">{st.minutes} {t("group.lesson.min")}</span>
                  </div>
                  <p className="mt-2 leading-relaxed text-sand-800" dir={useAr && st.body_ar ? "rtl" : "ltr"}>
                    {useAr && st.body_ar ? st.body_ar : st.body_en}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>

      {/* Action principale. */}
      {isTeacher && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-sand-200 bg-white p-4 print:hidden">
          {action.status === "proposed" ? (
            <>
              <p className="text-sm text-sand-600">{t("group.taught.hint")}</p>
              <div className="flex gap-2">
                <Button variant="ghost" disabled={busy !== null} onClick={() => run("skip", () => api.planActionDismiss(action.id))}>{t("group.skip")}</Button>
                <Button variant="accent" disabled={busy !== null || active.length === 0} onClick={taught}>{t("group.taught")}</Button>
              </div>
            </>
          ) : action.status === "done" ? (
            <>
              <Chip className="bg-teal-50 text-teal-700 ring-teal-100">{t("group.taught.done")} {action.done_at?.slice(0, 10)}</Chip>
              <Link href={`/teacher/${classroomId}/actions/${action.id}/proof`} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white">{t("group.proof")}</Link>
            </>
          ) : (
            <Chip className="bg-sand-100 text-sand-500 ring-sand-200">{t("week.action.dismissed")}</Chip>
          )}
        </div>
      )}
    </div>
  );
}
