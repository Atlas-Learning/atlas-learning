"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Card, Chip, EmptyState, ErrorPanel, Loading, SectionTitle, cx } from "@/components/ui";
import { StandardBadge } from "@/components/StandardBadge";
import { api } from "@/lib/api";
import type { ClassDigest, ClassGap, ClassMatrix, StudentRow } from "@/lib/types";
import { CELL_STYLE, StateDot } from "@/components/MasteryRange";
import type { DictKey } from "@/lib/i18n";
import { eloToLevel } from "@/lib/mastery";

export default function TeacherClassPage({ params }: { params: { classroomId: string } }) {
  return (
    <AppShell>
      <ClassView classroomId={params.classroomId} />
    </AppShell>
  );
}

function ClassView({ classroomId }: { classroomId: string }) {
  const { t } = useLang();
  const [gaps, setGaps] = useState<ClassGap[] | null>(null);
  const [students, setStudents] = useState<StudentRow[] | null>(null);
  const [digest, setDigest] = useState<ClassDigest | null>(null);
  const [matrix, setMatrix] = useState<ClassMatrix | null>(null);
  const [className, setClassName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.classGaps(classroomId), api.classStudents(classroomId), api.classDigest(classroomId)])
      .then(([g, s, d]) => {
        setGaps(g.gaps);
        setStudents(s.students);
        setClassName(s.name);
        setDigest(d);
      })
      .catch((e) => setError(e.message));
    api.classroomMatrix(classroomId).then(setMatrix).catch(() => setMatrix(null));
  }, [classroomId]);

  if (error) return <ErrorPanel detail={error} />;
  if (!gaps || !students) return <Loading label={t("common.loading")} />;

  const hasData = students.some((s) => s.n_measured > 0);

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium text-brand-600">{className}</p>
        <h1 className="mt-0.5 text-2xl font-semibold text-sand-800">{t("class.title")}</h1>
        <p className="mt-1 text-sm text-sand-500">{t("class.subtitle")}</p>
        <Link href={`/teacher/${classroomId}/week`} className="mt-2 inline-block text-sm font-medium text-brand-600 hover:underline">
          {t("class.week.link")}
        </Link>
      </header>

      {!hasData ? (
        <EmptyState title={t("empty.class.title")} body={t("empty.class.body")} />
      ) : (
        <div className="space-y-6">
        {digest && <DigestBanner digest={digest} />}
        {matrix && matrix.competencies.length > 0 && <MatrixCard matrix={matrix} classroomId={classroomId} />}
        <div className="grid gap-6 lg:grid-cols-5">
          {/* Priorités de classe — regroupées par cause racine, triées par fréquence. */}
          <Card className="p-5 lg:col-span-3">
            <SectionTitle title={t("class.gaps.title")} />
            <ul className="space-y-3">
              {gaps.map((g, i) => (
                <PriorityRow key={g.root_cause} gap={g} rank={i + 1} />
              ))}
              {gaps.length === 0 && (
                <li className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                  {t("profile.nogaps.body")}
                </li>
              )}
            </ul>
          </Card>

          {/* Liste des élèves. */}
          <Card className="p-5 lg:col-span-2">
            <SectionTitle title={`${t("class.students.title")} · ${students.length}`} />
            <div className="overflow-hidden rounded-xl ring-1 ring-sand-200">
              <table className="w-full text-sm">
                <thead className="bg-sand-50 text-xs uppercase tracking-wide text-sand-500">
                  <tr>
                    <th className="px-3 py-2 text-start font-medium">{t("class.col.student")}</th>
                    <th className="px-2 py-2 text-center font-medium">{t("class.col.level")}</th>
                    <th className="px-2 py-2 text-center font-medium">{t("class.col.gaps")}</th>
                    <th className="px-2 py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-sand-100">
                  {students.map((s) => (
                    <tr key={s.student_id} className="hover:bg-sand-25">
                      <td className="px-3 py-2.5 font-medium text-sand-800" data-ltr>
                        {s.external_ref}
                      </td>
                      <td className="px-2 py-2.5 text-center">
                        <span className="num text-sand-600">{eloToLevel(s.mean_ability)}</span>
                      </td>
                      <td className="px-2 py-2.5 text-center">
                        {s.n_measured === 0 ? (
                          <span className="text-xs text-sand-400">{t("common.notmeasured")}</span>
                        ) : (
                          <Chip
                            className={cx(
                              "num",
                              s.n_gaps > 0
                                ? "bg-gold-50 text-gold-700 ring-gold-200"
                                : "bg-emerald-50 text-emerald-800 ring-emerald-200",
                            )}
                          >
                            {s.n_gaps}
                          </Chip>
                        )}
                      </td>
                      <td className="px-2 py-2.5 text-end">
                        <Link
                          href={`/teacher/${classroomId}/s/${s.student_id}`}
                          className="text-sm font-medium text-brand-600 hover:underline"
                        >
                          {t("class.open")}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
        </div>
      )}
    </div>
  );
}

// E5 · Matrice élèves × compétences : quatre états, pas de scores, pas de rouge (B5).
function MatrixCard({ matrix, classroomId }: { matrix: ClassMatrix; classroomId: string }) {
  const { t, lang } = useLang();
  const states = ["mastered", "progress", "estimated", "unmeasured"] as const;
  return (
    <Card className="p-5">
      <SectionTitle title={t("matrix.title")} subtitle={t("matrix.subtitle")} />
      <div className="mb-3 flex flex-wrap gap-3 text-xs text-sand-500">
        {states.map((s) => (
          <span key={s} className="flex items-center gap-1.5"><StateDot state={s} /> {t(`matrix.legend.${s}` as DictKey)}</span>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="text-xs">
          <thead>
            <tr>
              <th className="sticky start-0 bg-white px-2 py-1 text-start font-medium text-sand-500">{t("class.col.student")}</th>
              {matrix.competencies.map((c) => (
                <th key={c.code} className="px-1 py-1 font-normal text-sand-400" title={lang === "ar" ? c.label_ar : c.label_en}>
                  <span className="block max-w-[3.5rem] truncate" data-ltr>{c.code.split(".").slice(-1)[0]}</span>
                </th>
              ))}
              <th className="px-2 py-1 font-medium text-sand-500">{t("matrix.legend.mastered")}</th>
            </tr>
          </thead>
          <tbody>
            {matrix.students.map((st) => (
              <tr key={st.student_id} className="hover:bg-sand-25">
                <td className="sticky start-0 bg-white px-2 py-1">
                  <Link href={`/teacher/${classroomId}/s/${st.student_id}`} className="num font-medium text-brand-700 hover:underline">{st.external_ref}</Link>
                </td>
                {matrix.competencies.map((c) => {
                  const cell = st.cells[c.code];
                  return (
                    <td key={c.code} className="px-1 py-1 text-center" title={`${lang === "ar" ? c.label_ar : c.label_en} · ${t(`matrix.legend.${cell.state}` as DictKey)}`}>
                      <span className={cx("mx-auto block h-4 w-6 rounded-sm", CELL_STYLE[cell.state].bg)}
                        style={{ backgroundImage: cell.state === "estimated" ? "repeating-linear-gradient(45deg, rgba(255,255,255,.6) 0 4px, transparent 4px 8px)" : undefined }} />
                    </td>
                  );
                })}
                <td className="num px-2 py-1 text-center text-sand-600">{st.n_mastered}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function DigestBanner({ digest }: { digest: ClassDigest }) {
  const { t, lang } = useLang();
  const top = digest.top_priority;
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionTitle title={t("digest.title")} />
        <div className="flex items-center gap-4 text-sm text-sand-600">
          <span>
            <span className="num font-semibold text-sand-800">{digest.n_active_students}</span>{" "}
            {t("digest.active")}
          </span>
          <span>
            <span className="num font-semibold text-sand-800">{digest.n_responses}</span>{" "}
            {t("digest.answers")}
          </span>
        </div>
      </div>

      {top && (
        <div className="mt-3 rounded-xl border border-brand-200 bg-brand-50/50 p-3.5">
          <p className="text-xs font-medium uppercase tracking-wide text-brand-600">
            {t("digest.priority")}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-sm font-medium text-sand-800">
            {lang === "ar" ? top.root_cause_label_ar : top.root_cause_label_en}
            {/* B4 : code standard si vue curriculaire — absent en vue ATLAS. */}
            <StandardBadge standard={top.standard} />
            <span className="num text-xs font-normal text-sand-500">
              · {top.student_count} {t("class.gaps.affected")}
            </span>
          </p>
        </div>
      )}

      <div className="mt-3">
        <p className="text-xs font-medium uppercase tracking-wide text-sand-500">
          {t("digest.emerging")}
        </p>
        <p className="text-xs text-sand-400">
          {t("digest.emerging.hint").replace("{n}", String(digest.window_days))}
        </p>
        {digest.emerging_gaps.length === 0 ? (
          <p className="mt-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            {t("digest.quiet")}
          </p>
        ) : (
          <div className="mt-2 flex flex-wrap gap-2">
            {digest.emerging_gaps.map((g) => (
              <Chip key={g.root_cause} className="bg-gold-50 text-gold-700 ring-gold-200">
                {lang === "ar" ? g.root_cause_label_ar : g.root_cause_label_en}
                {/* B4 : code standard inline (le chip est déjà un badge) — absent en vue ATLAS. */}
                {g.standard && (
                  <span
                    className="font-mono text-[10px]"
                    title={lang === "ar" ? g.standard.wording_ar : g.standard.wording_en}
                    data-ltr
                  >
                    {g.standard.code}
                  </span>
                )}
                <span className="num ms-1">· {g.student_count}</span>
              </Chip>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

function PriorityRow({ gap, rank }: { gap: ClassGap; rank: number }) {
  const { t, lang } = useLang();
  const rootLabel = lang === "ar" ? gap.root_cause_label_ar : gap.root_cause_label_en;
  const gapLabel = lang === "ar" ? gap.gap_label_ar : gap.gap_label_en;
  // Phrase localisée (jamais la chaîne brute du back, qui contient des codes).
  const line = gap.is_self
    ? lang === "ar"
      ? `${gap.student_count} طلاب يحتاجون العمل مباشرة على هذه المهارة.`
      : `${gap.student_count} students need to work on this skill directly.`
    : lang === "ar"
      ? `${gap.student_count} طلاب متعثّرون في «${gapLabel}» بسبب هذا المتطلّب السابق.`
      : `${gap.student_count} students are blocked on “${gapLabel}” because of this prerequisite.`;

  return (
    <li className="flex items-start gap-3 rounded-xl border border-sand-200 bg-white p-3.5">
      <span className="num mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-600 text-xs font-semibold text-white">
        {rank}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <p className="flex min-w-0 flex-wrap items-center gap-1.5 font-medium text-sand-800">
            {rootLabel}
            {/* B4 : code standard si vue curriculaire — absent en vue ATLAS. */}
            <StandardBadge standard={gap.standard} />
          </p>
          <Chip className="num shrink-0 bg-gold-50 text-gold-700 ring-gold-200">
            {gap.student_count} {t("class.gaps.affected")}
          </Chip>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-sand-500">{line}</p>
      </div>
    </li>
  );
}
