"use client";

import { useState } from "react";
import { useLang } from "@/components/LanguageProvider";
import { Button } from "@/components/ui";
import { Logo } from "@/components/AppShell";
import { api } from "@/lib/api";

// Accès « sans SSO » pour les rôles attribués hors roster (dept_lead, group_admin ; le super
// admin aussi) : email → lien magique single-use → /login/confirm. Réponse constante côté API :
// la page n'indique jamais si le compte existe (docs/refonte/06-attribution-des-roles.md).
export default function StaffRequestPage() {
  const { t, lang, toggle } = useLang();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.staffRequestLink(email);
    } catch {
      /* réponse constante : même écran */
    } finally {
      setSent(true);
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-sand-50 px-6 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Logo />
            <span className="text-lg font-semibold text-sand-800">{t("app.name")}</span>
          </div>
          <button onClick={toggle} className="text-sm font-medium text-brand-600 hover:underline">
            {lang === "en" ? "العربية" : "English"}
          </button>
        </div>

        {sent ? (
          <div className="rounded-xl border border-sand-200 bg-white p-6 text-sm text-sand-700">
            <p className="font-medium">{t("staff.login.sent.title")}</p>
            <p className="mt-1 text-sand-500">{t("staff.login.sent.body")}</p>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <h1 className="text-xl font-semibold text-sand-800">{t("staff.login.title")}</h1>
            <p className="text-sm text-sand-500">{t("staff.login.intro")}</p>
            <input
              type="email"
              required
              value={email}
              onChange={(ev) => setEmail(ev.target.value)}
              placeholder={t("login.email")}
              className="w-full rounded-xl border border-sand-300 bg-white px-3.5 py-2.5 text-sm outline-none focus:border-brand-400"
              autoComplete="email"
            />
            <Button type="submit" disabled={busy} className="w-full">
              {t("staff.login.submit")}
            </Button>
          </form>
        )}

        <p className="mt-6 text-center text-sm text-sand-500">
          <a href="/login" className="font-medium text-brand-600 hover:underline">
            {t("common.back")}
          </a>
        </p>
      </div>
    </div>
  );
}
