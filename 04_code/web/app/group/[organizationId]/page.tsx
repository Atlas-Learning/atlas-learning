"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell, useMe } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Card, EmptyState, SectionTitle } from "@/components/ui";
import { api } from "@/lib/api";
import type { SchoolOverview } from "@/lib/types";

// G1 · Vue multi-écoles — structure (ticket A1). Le contenu « causes communes entre écoles »
// arrive avec `GET /organizations/{id}/overview` au ticket D3. En attendant, la page s'appuie
// sur /me (écoles lisibles par le group_admin) et sur les agrégats école existants, dans les
// limites du RBAC : jamais de classe, jamais d'élève nominatif, jamais de résultat par enseignant.
export default function GroupPage({ params }: { params: { organizationId: string } }) {
  return (
    <AppShell>
      <GroupView organizationId={params.organizationId} />
    </AppShell>
  );
}

type Summary = { status: "loading" } | { status: "ok"; data: SchoolOverview } | { status: "error" };

function GroupView({ organizationId }: { organizationId: string }) {
  const { t } = useLang();
  const me = useMe();
  const [summaries, setSummaries] = useState<Record<string, Summary>>({});

  const org = me?.organizations.find((o) => o.id === organizationId) ?? me?.organizations[0];
  const schools = me?.schools ?? [];

  useEffect(() => {
    if (schools.length === 0) return;
    setSummaries(Object.fromEntries(schools.map((s) => [s.id, { status: "loading" } as Summary])));
    schools.forEach((s) => {
      api
        .schoolOverview(s.id)
        .then((data) => setSummaries((prev) => ({ ...prev, [s.id]: { status: "ok", data } })))
        .catch(() => setSummaries((prev) => ({ ...prev, [s.id]: { status: "error" } })));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schools.map((s) => s.id).join(",")]);

  const loaded = Object.values(summaries).filter((s): s is { status: "ok"; data: SchoolOverview } => s.status === "ok");
  const nStudents = loaded.reduce((a, s) => a + s.data.n_students, 0);
  const nClasses = loaded.reduce((a, s) => a + s.data.classes.length, 0);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-sand-800">{org?.name ?? t("group.title")}</h1>
        <p className="mt-1 text-sm text-sand-500">{t("group.subtitle")}</p>
      </header>

      <div className="grid grid-cols-3 gap-3">
        <Kpi value={schools.length} label={t("group.kpi.schools")} />
        <Kpi value={nStudents} label={t("group.kpi.students")} />
        <Kpi value={nClasses} label={t("group.kpi.classes")} />
      </div>

      {schools.length === 0 ? (
        <EmptyState title={t("group.title")} body={t("group.noschool")} />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {schools.map((s) => {
            const sum = summaries[s.id];
            return (
              <li key={s.id}>
                <Card className="flex h-full flex-col justify-between p-5">
                  <div>
                    <p className="text-base font-semibold text-sand-800">{s.name}</p>
                    {!sum || sum.status === "loading" ? (
                      <p className="mt-1 text-sm text-sand-400">{t("group.school.loading")}</p>
                    ) : sum.status === "error" ? (
                      <p className="mt-1 text-sm text-sand-400">{t("group.school.unavailable")}</p>
                    ) : (
                      <p className="num mt-1 text-sm text-sand-500">
                        {sum.data.n_students} {t("common.students")} · {sum.data.classes.length}{" "}
                        {t("group.kpi.classes").toLowerCase()}
                      </p>
                    )}
                    <p className="mt-2 text-xs text-sand-400">{t("group.unlocked.pending")}</p>
                  </div>
                  <Link
                    href={`/admin/${s.id}`}
                    className="mt-4 inline-flex w-fit rounded-lg bg-brand-50 px-3 py-1.5 text-sm font-medium text-brand-700 hover:bg-brand-100"
                  >
                    {t("group.school.open")}
                  </Link>
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      <Card className="p-5">
        <SectionTitle title={t("group.common.title")} />
        <EmptyState title={t("group.common.title")} body={t("group.common.body")} />
      </Card>
    </div>
  );
}

function Kpi({ value, label }: { value: number | string; label: string }) {
  return (
    <Card className="p-4">
      <p className="num text-2xl font-semibold text-brand-700">{value}</p>
      <p className="mt-0.5 text-xs text-sand-500">{label}</p>
    </Card>
  );
}
