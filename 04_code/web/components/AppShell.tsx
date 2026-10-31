"use client";

import { createContext, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useLang } from "@/components/LanguageProvider";
import { Loading, cx } from "@/components/ui";
import { api, ApiError, clearToken, getToken } from "@/lib/api";
import type { Me } from "@/lib/types";
import { DictKey } from "@/lib/i18n";

const MeCtx = createContext<Me | null>(null);
export const useMe = () => useContext(MeCtx);

interface NavItem {
  href: string;
  key: DictKey;
}

function navFor(me: Me): NavItem[] {
  const r = new Set(me.roles);
  const items: NavItem[] = [];
  if (r.has("teacher")) {
    const cls = me.classrooms[0];
    if (cls) items.push({ href: `/teacher/${cls.id}`, key: "nav.class" });
  }
  if (r.has("ped_admin") || r.has("super_admin")) {
    const school = me.schools[0];
    if (school) {
      items.push({ href: `/admin/${school.id}`, key: "nav.school" });
      items.push({ href: `/admin/${school.id}/classes`, key: "nav.classes" });
      items.push({ href: `/admin/${school.id}/report`, key: "nav.report" });
    }
  }
  // Refonte A1 : coordinateur (ses niveaux dans son école) et groupe scolaire (ses écoles).
  if (r.has("dept_lead")) {
    const schoolId = me.department_scopes[0]?.school_id;
    if (schoolId) items.push({ href: `/department/${schoolId}`, key: "nav.department" });
  }
  if (r.has("group_admin")) {
    const org = me.organizations[0];
    if (org) items.push({ href: `/group/${org.id}`, key: "nav.group" });
  }
  if (r.has("it_admin")) items.push({ href: "/it", key: "nav.security" });
  if (r.has("linguist")) items.push({ href: "/linguist", key: "nav.linguist" });
  if (r.has("student") && me.own_student_id) items.push({ href: "/student", key: "nav.session" });
  if (r.has("parent") && me.child_student_ids[0])
    items.push({ href: `/parent/${me.child_student_ids[0]}`, key: "nav.trajectory" });
  return items;
}

export function AppShell({ children, narrow }: { children: React.ReactNode; narrow?: boolean }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api
      .me()
      .then(setMe)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          clearToken();
          router.replace("/login");
        } else {
          setError(e.message);
        }
      });
  }, [router]);

  if (error) return <CenterMessage>{error}</CenterMessage>;
  if (!me) return <FullLoading />;

  return (
    <MeCtx.Provider value={me}>
      <div className="min-h-screen bg-sand-50">
        <Header me={me} />
        <main className={cx("mx-auto px-4 py-6 sm:px-6", narrow ? "max-w-2xl" : "max-w-6xl")}>
          {children}
        </main>
      </div>
    </MeCtx.Provider>
  );
}

function Header({ me }: { me: Me }) {
  const { t, toggle, lang } = useLang();
  const router = useRouter();
  const pathname = usePathname();
  const items = navFor(me);

  function signOut() {
    clearToken();
    router.replace("/login");
  }

  return (
    <header className="sticky top-0 z-20 border-b border-sand-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 sm:px-6">
        <Link href="/" className="flex items-center gap-2">
          <Logo />
          <span className="font-semibold text-brand-800">{t("app.name")}</span>
        </Link>

        <nav className="ms-2 hidden items-center gap-1 sm:flex">
          {items.map((it) => {
            const active = pathname === it.href || pathname.startsWith(it.href + "/");
            return (
              <Link
                key={it.href}
                href={it.href}
                className={cx(
                  "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  active ? "bg-brand-50 text-brand-700" : "text-sand-500 hover:bg-sand-100 hover:text-sand-700",
                )}
              >
                {t(it.key)}
              </Link>
            );
          })}
        </nav>

        <div className="ms-auto flex items-center gap-2">
          <button
            onClick={toggle}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-sand-600 ring-1 ring-sand-300 hover:bg-sand-50"
            aria-label="Switch language"
          >
            {lang === "en" ? "العربية" : "English"}
          </button>
          <button
            onClick={signOut}
            className="rounded-lg px-3 py-1.5 text-sm text-sand-500 hover:bg-sand-100 hover:text-sand-700"
          >
            {t("nav.signout")}
          </button>
        </div>
      </div>

      {/* Nav mobile (sous le header). */}
      {items.length > 0 && (
        <nav className="flex gap-1 overflow-x-auto border-t border-sand-100 px-4 py-2 sm:hidden">
          {items.map((it) => {
            const active = pathname === it.href || pathname.startsWith(it.href + "/");
            return (
              <Link
                key={it.href}
                href={it.href}
                className={cx(
                  "whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium",
                  active ? "bg-brand-50 text-brand-700" : "text-sand-500",
                )}
              >
                {t(it.key)}
              </Link>
            );
          })}
        </nav>
      )}
    </header>
  );
}

export function Logo() {
  return (
    <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand-600 text-white">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" strokeLinejoin="round" />
        <path d="M12 8v8M8 10v4M16 10v4" strokeLinecap="round" />
      </svg>
    </span>
  );
}

function FullLoading() {
  const { t } = useLang();
  return (
    <div className="grid min-h-screen place-items-center bg-sand-50">
      <Loading label={t("common.loading")} />
    </div>
  );
}

function CenterMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen place-items-center bg-sand-50 px-4">
      <div className="rounded-2xl bg-white px-6 py-5 text-sm text-danger shadow-card">{children}</div>
    </div>
  );
}
