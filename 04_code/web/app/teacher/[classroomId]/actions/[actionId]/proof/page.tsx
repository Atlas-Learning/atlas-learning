"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppShell, useMe } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Button, ErrorPanel, Loading } from "@/components/ui";
import { ProofCard } from "@/components/ProofCard";
import { api, ApiError } from "@/lib/api";
import type { ProofCardData } from "@/lib/types";

// E4 · Carte de preuve (B5) — maquette Proof.dc.html.
export default function ProofPage({ params }: { params: { classroomId: string; actionId: string } }) {
  return (
    <AppShell>
      <ProofView classroomId={params.classroomId} actionId={params.actionId} />
    </AppShell>
  );
}

function ProofView({ classroomId, actionId }: { classroomId: string; actionId: string }) {
  const { t, lang } = useLang();
  const me = useMe();
  const router = useRouter();
  const isTeacher = me?.roles.includes("teacher") && me.classrooms.some((c) => c.id === classroomId);
  const [proof, setProof] = useState<ProofCardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.planActionProof(actionId).then(setProof).catch((e) => setError(e instanceof ApiError ? e.detail : (e as Error).message));
  }, [actionId]);

  if (error) return <ErrorPanel detail={error} />;
  if (!proof) return <Loading label={t("common.loading")} />;

  const recheck = proof.recheck;
  return (
    <div className="space-y-6">
      <Link href={`/teacher/${classroomId}/week`} className="text-sm font-medium text-brand-600 hover:underline">← {t("week.title")}</Link>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-sand-800">{t("proof.title")}</h1>
          <p className="mt-1 text-sm text-sand-500">{proof.root_cause ? (lang === "ar" ? proof.root_cause.label_ar : proof.root_cause.label_en) : ""}</p>
        </div>
        <div className="flex gap-2">
          {isTeacher && recheck && recheck.status !== "closed" && (
            <Button variant="accent" onClick={async () => {
              if (recheck.status === "scheduled") await api.startCheckin(recheck.id);
              router.push(`/teacher/${classroomId}/checkin/${recheck.id}`);
            }}>
              {recheck.status === "scheduled" ? t("week.recheck.start") : t("week.recheck.resume")}
            </Button>
          )}
          <Button variant="outline" onClick={() => { navigator.clipboard?.writeText(window.location.href); setCopied(true); }}>
            {copied ? t("proof.shared") : t("proof.share")}
          </Button>
        </div>
      </header>
      <ProofCard proof={proof} />
    </div>
  );
}
