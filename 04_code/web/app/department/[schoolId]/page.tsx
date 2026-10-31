"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { AppShell, useMe } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Card, EmptyState, SectionTitle, cx } from "@/components/ui";

// C1 · Revue de département — structure (ticket A1). Le contenu (causes racines communes ×
// classes, actions et effet mesuré, décision consignée) arrive avec
// `GET /schools/{id}/department-review` au ticket D1. En attendant : les niveaux du
// coordinateur dans cette école (depuis /me) et les classes de chaque niveau, ouvrables dans la
// vue classe existante (le RBAC autorise le dept_lead sur ces classes et sur rien d'autre).
export default function DepartmentPage({ params }: { params: { schoolId: string } }) {
  return (
    <AppShell>
      <DepartmentView schoolId={params.schoolId} />
    </AppShell>
  );
}

function DepartmentView({ schoolId }: { schoolId: string }) {
  const { t } = useLang();
  const me = useMe();

  const grades = useMemo(
    () =>
      (me?.department_scopes ?? [])
        .filter((d) => d.school_id === schoolId)
        .map((d) => d.grade)
        .sort((a, b) => a - b),
    [me, schoolId],
  );
  const [selected, setSelected] = useState<number | null>(null);
  const grade = selected ?? grades[0] ?? null;
  const school = me?.schools.find((s) => s.id === schoolId);
  const classes = (me?.classrooms ?? []).filter((c) => c.school_id === schoolId && c.grade === grade);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-sand-800">
          {t("department.title")}
          {school ? <span className="text-sand-400"> · {school.name}</span> : null}
        </h1>
        <p className="mt-1 text-sm text-sand-500">{t("department.subtitle")}</p>
      </header>

      {grades.length === 0 ? (
        <EmptyState title={t("department.title")} body={t("department.noscope")} />
      ) : (
        <>
          <div className="flex flex-wrap gap-2" role="tablist" aria-label={t("department.grade")}>
            {grades.map((g) => (
              <button
                key={g}
                role="tab"
                aria-selected={g === grade}
                onClick={() => setSelected(g)}
                className={cx(
                  "num rounded-lg px-3.5 py-1.5 text-sm font-medium ring-1 transition-colors",
                  g === grade
                    ? "bg-brand-600 text-white ring-brand-600"
                    : "bg-white text-sand-600 ring-sand-300 hover:bg-sand-50",
                )}
              >
                {t("department.grade")} {g}
              </button>
            ))}
          </div>

          <Card className="p-5">
            <SectionTitle title={t("department.classes")} />
            {classes.length === 0 ? (
              <p className="py-6 text-center text-sm text-sand-400">{t("department.noclass")}</p>
            ) : (
              <ul className="space-y-2">
                {classes.map((c) => (
                  <li
                    key={c.id}
                    className="flex items-center justify-between rounded-xl border border-sand-200 bg-white px-4 py-3"
                  >
                    <p className="font-medium text-sand-800">{c.name}</p>
                    <Link
                      href={`/teacher/${c.id}`}
                      className="rounded-lg bg-brand-50 px-3 py-1.5 text-sm font-medium text-brand-700 hover:bg-brand-100"
                    >
                      {t("department.open")}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card className="p-5">
            <SectionTitle title={t("department.review.title")} />
            <EmptyState title={t("department.review.title")} body={t("department.review.body")} />
          </Card>
        </>
      )}
    </div>
  );
}
