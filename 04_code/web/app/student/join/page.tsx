"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { useLang } from "@/components/LanguageProvider";
import { Button, Card } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

// S1 · Rejoindre (B5) — maquette Student-join.dc.html. Compte SSO déjà connecté + code.
export default function JoinPage() {
  return (
    <AppShell narrow>
      <JoinView />
    </AppShell>
  );
}

function JoinView() {
  const { t, lang } = useLang();
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function join() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.joinCheckin(code, lang);
      router.push(`/student?session=${r.session_id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setError(t("join.error.code"));
      else if (e instanceof ApiError && e.status === 403) setError(t("join.error.member"));
      else setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Card className="p-8 text-center">
      <h1 className="text-2xl font-semibold text-sand-800">{t("join.title")}</h1>
      <p className="mx-auto mt-2 max-w-md text-sand-500">{t("join.body")}</p>
      <input
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 4))}
        inputMode="numeric"
        autoFocus
        className="num mx-auto mt-6 block w-56 rounded-2xl border-2 border-sand-200 px-4 py-4 text-center text-4xl tracking-[0.4em] outline-none focus:border-brand-400"
        data-ltr
        aria-label={t("checkin.code")}
      />
      {error && <p className="mt-3 text-sm text-gold-700">{error}</p>}
      <Button variant="accent" className="mt-6 px-8 py-3 text-base" disabled={code.length !== 4 || busy} onClick={join}>
        {t("join.submit")}
      </Button>
    </Card>
  );
}
