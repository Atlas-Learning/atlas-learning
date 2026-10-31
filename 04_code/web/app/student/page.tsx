"use client";

import { useEffect, useState } from "react";
import { AppShell, useMe } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Button, Card, ErrorPanel, Spinner, cx } from "@/components/ui";
import { api } from "@/lib/api";
import type { ItemContent, NextItem, Trajectory } from "@/lib/types";

export default function StudentPage() {
  return (
    <AppShell narrow>
      <SessionFlow />
    </AppShell>
  );
}

type Phase = "intro" | "question" | "feedback" | "done";

function SessionFlow() {
  const me = useMe();
  const { t, lang } = useLang();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [item, setItem] = useState<NextItem | null>(null);
  const [phase, setPhase] = useState<Phase>("intro");
  const [selected, setSelected] = useState<string>("");
  const [lastCorrect, setLastCorrect] = useState<boolean | null>(null);
  const [pendingNext, setPendingNext] = useState<NextItem | null>(null);
  const [answered, setAnswered] = useState(0);
  const [skills, setSkills] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startTraj, setStartTraj] = useState<Trajectory | null>(null);
  const [endTraj, setEndTraj] = useState<Trajectory | null>(null);

  const studentId = me?.own_student_id;

  // S1 → S2 : une session de check-in déjà ouverte (?session=) démarre sans intro.
  useEffect(() => {
    if (!studentId) return;
    const sid = new URLSearchParams(window.location.search).get("session");
    if (!sid || sessionId) return;
    api.studentTrajectory(studentId).then(setStartTraj).catch(() => undefined);
    setSessionId(sid);
    api.nextItem(sid).then((first) => { handleNext(first); setPhase(first.done ? "done" : "question"); })
      .catch((e) => setError((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studentId]);

  // S3 : à la fin, l'état après pour mettre en avant ce qui vient d'être débloqué.
  useEffect(() => {
    if (phase !== "done" || !studentId) return;
    api.studentTrajectory(studentId).then(setEndTraj).catch(() => undefined);
  }, [phase, studentId]);

  async function begin() {
    if (!studentId) return;
    setBusy(true);
    setError(null);
    try {
      api.studentTrajectory(studentId).then(setStartTraj).catch(() => undefined);
      const { session_id } = await api.startSession(studentId);
      setSessionId(session_id);
      const first = await api.nextItem(session_id);
      handleNext(first);
      setPhase(first.done ? "done" : "question");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function handleNext(next: NextItem) {
    if (next.done) {
      setPhase("done");
      setItem(null);
    } else {
      setItem(next);
      setSelected("");
      if (next.competency_id) setSkills((s) => new Set(s).add(next.competency_id!));
    }
  }

  async function submit() {
    if (!sessionId || !item?.item_id || !selected) return;
    setBusy(true);
    try {
      const res = await api.submitResponse(sessionId, item.item_id, selected, lang);
      setLastCorrect(res.was_correct ?? null);
      setAnswered((n) => n + 1);
      // On garde l'item courant pour le feedback ; le payload contient déjà le SUIVANT.
      setPendingNext(res);
      setPhase("feedback");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function advance() {
    const next = pendingNext;
    setLastCorrect(null);
    setPendingNext(null);
    if (next) handleNext(next);
    if (next && !next.done) setPhase("question");
    else setPhase("done");
  }

  if (!studentId) return <ErrorPanel detail={t("error.generic")} />;
  if (error) return <ErrorPanel detail={error} />;

  if (phase === "intro") {
    return (
      <Card className="p-8 text-center">
        <div className="mx-auto mb-4 grid h-16 w-16 place-items-center rounded-2xl bg-brand-50 text-brand-500">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" strokeLinejoin="round" />
          </svg>
        </div>
        <h1 className="text-2xl font-semibold text-sand-800">{t("session.start")}</h1>
        <p className="mx-auto mt-2 max-w-md text-sand-500">{t("session.start.body")}</p>
        <Button variant="accent" className="mt-6 px-8 py-3 text-base" disabled={busy} onClick={begin}>
          {busy ? <Spinner /> : t("session.begin")}
        </Button>
        <p className="mt-4 text-sm"><a href="/student/join" className="font-medium text-brand-600 hover:underline">{t("join.link")}</a></p>
      </Card>
    );
  }

  if (phase === "done") {
    const before = new Set((startTraj?.mastered ?? []).map((m) => m.label_en));
    const unlocked = (endTraj?.mastered ?? []).filter((m) => !before.has(m.label_en));
    const lbl = (m: { label_en: string; label_ar: string }) => (lang === "ar" ? m.label_ar : m.label_en);
    return (
      <Card className="p-8 text-center">
        {/* S3 · Débloqué : or pour l'accompli, puis en progrès et prochaine étape. Jamais de note. */}
        {unlocked.length > 0 && (
          <div className="mx-auto mb-6 max-w-md rounded-2xl bg-gold-50 p-5 ring-1 ring-gold-200">
            <p className="text-xs font-semibold uppercase tracking-wide text-gold-700">{t("done.unlocked")}</p>
            <ul className="mt-2 space-y-1">
              {unlocked.map((m) => <li key={m.label_en} className="text-lg font-semibold text-gold-800">✦ {lbl(m)}</li>)}
            </ul>
          </div>
        )}
        {endTraj && unlocked.length === 0 && <p className="mx-auto mb-4 max-w-md text-sm text-sand-500">{t("done.nothing")}</p>}
        {endTraj && (endTraj.closing_gaps.length > 0 || endTraj.next_step) && (
          <div className="mx-auto mb-6 grid max-w-md gap-3 text-start sm:grid-cols-2">
            {endTraj.closing_gaps.length > 0 && (
              <div className="rounded-xl bg-sand-50 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-gold-700">{t("done.progress")}</p>
                <ul className="mt-1 text-sm text-sand-700">{endTraj.closing_gaps.slice(0, 3).map((g) => <li key={g.label_en}>{lbl(g)}</li>)}</ul>
              </div>
            )}
            {endTraj.next_step && (
              <div className="rounded-xl bg-brand-50 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">{t("done.next")}</p>
                <p className="mt-1 text-sm text-sand-700">{lang === "ar" ? endTraj.next_step.skill_label_ar : endTraj.next_step.skill_label_en}</p>
              </div>
            )}
          </div>
        )}
        <div className="mx-auto mb-4 grid h-16 w-16 place-items-center rounded-full bg-emerald-50 text-mastered">
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <h1 className="text-2xl font-semibold text-sand-800">{t("session.done.title")}</h1>
        <p className="mx-auto mt-2 max-w-md text-sand-500">{t("session.done.body")}</p>
        <div className="mx-auto mt-6 grid max-w-xs grid-cols-2 gap-3">
          <Stat value={answered} label={t("session.progress") + "s"} />
          <Stat value={skills.size} label={t("session.done.practised")} />
        </div>
        <Button
          variant="outline"
          className="mt-6"
          onClick={() => {
            setSessionId(null);
            setAnswered(0);
            setSkills(new Set());
            setPhase("intro");
          }}
        >
          {t("session.done.again")}
        </Button>
      </Card>
    );
  }

  // question / feedback
  const content: ItemContent | null =
    (lang === "ar" && item?.content_ar) ? item!.content_ar! : item?.content_en ?? null;
  const showFeedback = phase === "feedback";

  return (
    <div>
      <div className="mb-4 flex items-center justify-between text-sm text-sand-500">
        <span className="num">
          {t("session.progress")} {answered + (showFeedback ? 0 : 1)}
        </span>
      </div>

      <Card className="p-6 sm:p-8">
        <p className="text-xl font-medium leading-relaxed text-sand-800 sm:text-2xl">{content?.stem}</p>

        {/* MCQ — grandes cibles tactiles. */}
        {item?.answer_format === "MCQ" && Array.isArray(content?.options) && (
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {content!.options!.map((opt) => {
              const active = selected === opt;
              const correctOpt = showFeedback && active && lastCorrect;
              const wrongOpt = showFeedback && active && lastCorrect === false;
              return (
                <button
                  key={opt}
                  disabled={showFeedback}
                  onClick={() => setSelected(opt)}
                  className={cx(
                    "num rounded-2xl border-2 px-5 py-5 text-center text-lg font-medium transition-colors",
                    !active && "border-sand-200 bg-white text-sand-700 hover:border-brand-300",
                    active && !showFeedback && "border-brand-500 bg-brand-50 text-brand-800",
                    correctOpt && "border-mastered bg-emerald-50 text-emerald-800",
                    // « à travailler » neutre/ambré, pas de rouge punitif côté élève (Brief §4).
                    wrongOpt && "border-gold-400 bg-gold-50 text-gold-700",
                  )}
                >
                  {opt}
                </button>
              );
            })}
          </div>
        )}

        {/* NUMERIC / SHORT — saisie. */}
        {(item?.answer_format === "NUMERIC" || item?.answer_format === "SHORT") && (
          <div className="mt-6">
            <label className="mb-1.5 block text-sm font-medium text-sand-600">{t("session.your.answer")}</label>
            <input
              value={selected}
              disabled={showFeedback}
              inputMode={item.answer_format === "NUMERIC" ? "decimal" : "text"}
              onChange={(e) => setSelected(e.target.value)}
              className="num w-full rounded-2xl border-2 border-sand-200 px-5 py-4 text-center text-xl outline-none focus:border-brand-400"
              data-ltr
            />
          </div>
        )}

        {/* Feedback bienveillant. */}
        {showFeedback && (
          <div
            className={cx(
              "mt-6 flex items-center gap-3 rounded-2xl px-5 py-4",
              lastCorrect ? "bg-emerald-50 text-emerald-800" : "bg-gold-50 text-gold-700",
            )}
          >
            <span className="text-2xl">{lastCorrect ? "🎉" : "💡"}</span>
            <span className="font-medium">
              {lastCorrect ? t("session.correct") : t("session.incorrect")}
            </span>
          </div>
        )}

        <div className="mt-6 flex justify-end">
          {!showFeedback ? (
            <Button variant="primary" className="px-8 py-3 text-base" disabled={!selected || busy} onClick={submit}>
              {busy ? <Spinner className="text-white" /> : t("session.submit")}
            </Button>
          ) : (
            <Button variant="accent" className="px-8 py-3 text-base" onClick={advance}>
              {t("session.next")}
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-xl bg-sand-50 px-3 py-4">
      <p className="num text-2xl font-semibold text-brand-700">{value}</p>
      <p className="mt-0.5 text-xs text-sand-500">{label}</p>
    </div>
  );
}
