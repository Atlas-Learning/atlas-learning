"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useLang } from "@/components/LanguageProvider";
import { Loading } from "@/components/ui";
import { api, ApiError, clearToken, getToken } from "@/lib/api";
import type { Me } from "@/lib/types";

// Route d'accueil : redirige chaque rôle vers son écran principal.
function landingFor(me: Me): string {
  const r = new Set(me.roles);
  if (r.has("teacher") && me.classrooms[0]) return `/teacher/${me.classrooms[0].id}`;
  if ((r.has("ped_admin") || r.has("super_admin")) && me.schools[0]) return `/admin/${me.schools[0].id}`;
  if (r.has("dept_lead") && me.department_scopes[0]) return `/department/${me.department_scopes[0].school_id}`;
  if (r.has("group_admin") && me.organizations[0]) return `/group/${me.organizations[0].id}`;
  if (r.has("it_admin")) return "/it";
  if (r.has("content_reviewer") || r.has("super_admin")) return "/ops/review"; // staff Atlas global (banque)
  if (r.has("linguist")) return "/linguist"; // staff Atlas global (relecture AR)
  if (r.has("student") && me.own_student_id) return "/student";
  if (r.has("parent") && me.child_student_ids[0]) return `/parent/${me.child_student_ids[0]}`;
  return "/login";
}

export default function Home() {
  const router = useRouter();
  const { t } = useLang();

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api
      .me()
      .then((me) => router.replace(landingFor(me)))
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) clearToken();
        router.replace("/login");
      });
  }, [router]);

  return (
    <div className="grid min-h-screen place-items-center bg-sand-50">
      <Loading label={t("common.loading")} />
    </div>
  );
}
