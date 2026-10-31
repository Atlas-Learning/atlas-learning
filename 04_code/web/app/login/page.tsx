"use client";

import { useEffect, useState } from "react";
import { useLang } from "@/components/LanguageProvider";
import { Logo } from "@/components/AppShell";
import { api } from "@/lib/api";

// Auth = SSO/OIDC uniquement (plus de mot de passe : cf. 0013_drop_direct_auth). Les boutons
// reflètent les providers activés côté serveur (/auth/providers). En prod : Keycloak (TOTP).
const PROVIDER_LABEL: Record<string, string> = {
  google: "Google",
  microsoft: "Microsoft",
  uaepass: "UAE PASS",
  generic: "Atlas",
};

export default function LoginPage() {
  const { t, toggle, lang } = useLang();
  const [providers, setProviders] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.authProviders().then((r) => setProviders(r.providers)).catch(() => setProviders([]));
    const qs = new URLSearchParams(window.location.search);
    if (qs.get("sso_error")) setError(t("login.sso.error"));
    if (qs.get("admin_error")) setError(t("login.link.error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* Panneau marque. */}
      <aside className="relative hidden flex-col justify-between bg-brand-800 p-10 text-white lg:flex">
        <div className="flex items-center gap-2">
          <Logo />
          <span className="text-lg font-semibold">{t("app.name")}</span>
        </div>
        <div className="max-w-md">
          <h1 className="text-3xl font-semibold leading-tight">{t("app.tagline")}</h1>
          <p className="mt-4 text-brand-100/80">
            {lang === "ar"
              ? "نُظهر مسار تعلّم الطفل — قابلًا للقياس والإثبات — مهارةً مهارة."
              : "We make a child's learning trajectory visible and provable — skill by skill."}
          </p>
        </div>
        <div className="h-1 w-24 rounded-full bg-gold-400" />
      </aside>

      {/* Connexion. */}
      <div className="flex flex-col items-center justify-center bg-sand-50 px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-6 flex items-center justify-between">
            <h2 className="text-xl font-semibold text-sand-800">{t("login.title")}</h2>
            <button onClick={toggle} className="text-sm font-medium text-brand-600 hover:underline">
              {lang === "en" ? "العربية" : "English"}
            </button>
          </div>

          {error && <p className="mb-4 text-sm text-danger">{error}</p>}

          {providers === null ? (
            <p className="text-sm text-sand-500">{t("common.loading")}</p>
          ) : providers.length === 0 ? (
            <p className="rounded-xl border border-sand-200 bg-white p-4 text-sm text-sand-500">
              {t("login.noprovider")}
            </p>
          ) : (
            <div className="space-y-2">
              {providers.map((key) => (
                // Navigation pleine page : /start redirige vers l'IdP (Keycloak → TOTP).
                <a
                  key={key}
                  href={`/api/oauth/${key}/start`}
                  className="block w-full rounded-xl bg-brand-600 px-3.5 py-3 text-center text-sm font-semibold text-white hover:bg-brand-700"
                >
                  {t("login.sso.with")} {PROVIDER_LABEL[key] ?? key}
                </a>
              ))}
            </div>
          )}

          <p className="mt-6 text-center text-sm text-sand-500">
            <a href="/parent" className="font-medium text-brand-600 hover:underline">
              {t("login.parent")}
            </a>
          </p>
          <p className="mt-2 text-center text-sm text-sand-500">
            <a href="/staff/login" className="font-medium text-brand-600 hover:underline">
              {t("login.staff")}
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}
