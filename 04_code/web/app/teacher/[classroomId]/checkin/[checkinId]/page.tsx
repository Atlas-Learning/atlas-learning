"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell, useMe } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Button, ErrorPanel, Loading } from "@/components/ui";
import { ProjectionLayout } from "@/components/ProjectionLayout";
import { api, ApiError } from "@/lib/api";
import type { CheckInInfo, CheckInProgress } from "@/lib/types";

// E2 · Check-in projeté (B5) — maquette Checkin.dc.html. Progression anonyme, rafraîchie.
export default function CheckinPage({ params }: { params: { classroomId: string; checkinId: string } }) {
  return (
    <AppShell>
      <CheckinView classroomId={params.classroomId} checkinId={params.checkinId} />
    </AppShell>
  );
}

function CheckinView({ classroomId, checkinId }: { classroomId: string; checkinId: string }) {
  const { t } = useLang();
  const me = useMe();
  const router = useRouter();
  const isTeacher = me?.roles.includes("teacher") && me.classrooms.some((c) => c.id === classroomId);
  const [info, setInfo] = useState<CheckInInfo | null>(null);
  const [progress, setProgress] = useState<CheckInProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    Promise.all([api.checkin(checkinId), api.checkinProgress(checkinId)])
      .then(([i, p]) => { setInfo(i); setProgress(p); })
      .catch((e) => setError(e instanceof ApiError ? e.detail : (e as Error).message));
  }, [checkinId]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, [refresh]);

  async function start() {
    setBusy(true);
    try { await api.startCheckin(checkinId); refresh(); } finally { setBusy(false); }
  }

  async function close() {
    setBusy(true);
    try {
      const r = await api.closeCheckin(checkinId);
      if (r.plan_id) router.push(`/teacher/${classroomId}/week`);
      else if (r.proof) router.push(`/teacher/${classroomId}/actions/${r.proof.action_id}/proof`);
      else refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <ErrorPanel detail={error} />;
  if (!info) return <Loading label={t("common.loading")} />;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-sand-800">
            {info.kind === "full" ? t("checkin.full") : t("checkin.targeted")}
          </h1>
          {info.status === "scheduled" && <p className="text-sm text-sand-500">{t("checkin.scheduled")}</p>}
          {info.status === "closed" && <p className="text-sm text-sand-500">{t("checkin.closed")}</p>}
        </div>
        <div className="flex gap-2">
          {info.status === "open" && (
            <Button variant="outline" onClick={() => setFullscreen(true)}>{t("checkin.project")}</Button>
          )}
          {isTeacher && info.status === "scheduled" && (
            <Button variant="accent" onClick={start} disabled={busy}>{t("checkin.start")}</Button>
          )}
          {isTeacher && info.status === "open" && (
            <Button variant="accent" onClick={close} disabled={busy}>{t("checkin.close")}</Button>
          )}
        </div>
      </header>
      {isTeacher && info.status === "open" && (
        <p className="text-xs text-sand-400">{info.kind === "full" ? t("checkin.close.full") : t("checkin.close.targeted")}</p>
      )}

      <ProjectionLayout code={info.code ?? null} progress={progress} fullscreen={fullscreen}>
        {fullscreen && (
          <div className="mt-8 flex justify-end gap-3">
            {isTeacher && info.status === "open" && (
              <Button variant="accent" onClick={close} disabled={busy}>{t("checkin.close")}</Button>
            )}
            <Button variant="outline" onClick={() => setFullscreen(false)}>{t("checkin.exit")}</Button>
          </div>
        )}
      </ProjectionLayout>
    </div>
  );
}
