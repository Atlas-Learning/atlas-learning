// Client API minimal. Le token Bearer est stocké en localStorage (démo MVP).
// Toutes les requêtes passent par /api/* (proxy Next → FastAPI), donc same-origin.

import type {
  ArCoverage,
  ArItem,
  CheckInClosed,
  CheckInInfo,
  CheckInProgress,
  ClassMatrix,
  ClassroomProofs,
  Lesson,
  LessonCoverage,
  LessonSummary,
  PlanAction,
  ProofCardData,
  UnlockHistory,
  WeeklyPlan,
  ClassDigest,
  ClassGap,
  CurriculumSettings,
  FrameworkCoverage,
  CurriculumDetail,
  CurriculumFrameworkRow,
  GraphNode,
  LinguistItem,
  LinguistQueue,
  Me,
  NextItem,
  RemediationPreview,
  ProofSurfaces,
  ReviewDetail,
  ReviewQueue,
  ReviewSource,
  RoleGrant,
  SchoolMailSettings,
  SchoolOverview,
  TutorExplanation,
  StudentProfile,
  StudentRow,
  Trajectory,
} from "./types";

const TOKEN_KEY = "atlas.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  // Un Authorization explicite (ex. jeton d'enrôlement MFA) prime sur le token de session.
  if (token && !headers["Authorization"]) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`/api${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface Integration {
  organization: {
    id: string; name: string; domain: string | null;
    seats: number | null; seats_used: number; over_capacity?: boolean;
  };
  integration: {
    provider: string; status: string; admin_email: string | null;
    last_sync_at: string | null; last_error: string | null;
  } | null;
}

export interface RosterRun {
  id: string; status: string; summary: string | null;
  created: number; updated: number; deactivated: number; errors: number;
  pending_deactivations: number;
  started_at: string | null; finished_at: string | null;
}

export interface AuditEntry {
  id: string; action: string; user_id: string | null; school_id: string | null;
  resource_type: string | null; resource_id: string | null; created_at: string | null;
}

export interface SetupState {
  steps: { key: string; done: boolean }[];
  done: number;
  total: number;
}

export interface Guardian {
  user_id: string;
  email: string;
  source: string;
}

export const api = {
  // Providers SSO activés côté serveur (pour afficher les bons boutons).
  authProviders: () => request<{ providers: string[] }>("/auth/providers"),

  // — Console IT admin : rostering —
  adminIntegration: () => request<Integration>("/admin/integration"),
  rosteringSync: (force = false) =>
    request<RosterRun>(`/admin/rostering/sync${force ? "?force=true" : ""}`, { method: "POST" }),
  rosteringRuns: () => request<{ runs: RosterRun[] }>("/admin/rostering/runs"),

  // — Console curriculum (B3) : framework d'affichage du tenant —
  adminCurriculum: () => request<CurriculumSettings>("/admin/curriculum"),
  adminSetCurriculum: (curriculum_view: string) =>
    request<{ curriculum_view: string }>("/admin/curriculum", {
      method: "POST",
      body: JSON.stringify({ curriculum_view }),
    }),

  // — Conformité PDPL —
  adminAudit: (limit = 8) => request<{ entries: AuditEntry[] }>(`/admin/audit?limit=${limit}`),
  adminExport: () => request<unknown>("/admin/export"),

  // — Onboarding guidé + accès parent —
  adminSetup: () => request<SetupState>("/admin/setup"),
  parentsInvite: () => request<{ invited: number }>("/admin/parents/invite", { method: "POST" }),
  // Lien magique staff « sans SSO » (super_admin, group_admin, dept_lead) — même flux que
  // l'accès éditeur : /admin/request-link → /admin/login → /admin/login/confirm.
  staffRequestLink: (email: string) =>
    request<{ ok: boolean }>("/admin/request-link", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  parentRequestLink: (email: string) =>
    request<{ ok: boolean }>("/parent/request-link", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  // Consommation du lien magique (single-use) : POST déclenché par un clic HUMAIN —
  // le GET du lien email ne consomme rien (anti-préchargement des scanners d'emails).
  parentLoginConfirm: (token: string) =>
    request<{ token: string }>("/parent/login/confirm", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  adminLoginConfirm: (token: string) =>
    request<{ token: string }>("/admin/login/confirm", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  // Lien magique du back-office linguiste (même contrat single-use / anti-préchargement).
  linguistRequestLink: (email: string) =>
    request<{ ok: boolean }>("/linguist/request-link", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  linguistLoginConfirm: (token: string) =>
    request<{ token: string }>("/linguist/login/confirm", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  parentChildren: () => request<{ children: { student_id: string; label: string }[] }>("/parent/children"),

  // — Tuteurs gérés par le staff —
  listGuardians: (studentId: string) =>
    request<{ guardians: Guardian[] }>(`/students/${studentId}/guardians`),
  addGuardian: (studentId: string, email: string) =>
    request<unknown>(`/students/${studentId}/guardians`, {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  removeGuardian: (studentId: string, userId: string) =>
    request<unknown>(`/students/${studentId}/guardians/${userId}`, { method: "DELETE" }),

  me: () => request<Me>("/me"),

  // Rôles attribués hors roster (refonte A1) — admin IT de l'organisation ou super admin.
  adminRoles: (organizationId: string) =>
    request<{ organization_id: string; grants: RoleGrant[] }>(`/admin/roles?organization_id=${organizationId}`),
  adminGrantRole: (body: {
    email: string;
    role: "dept_lead" | "group_admin";
    organization_id?: string;
    school_id?: string;
    grades?: number[];
  }) => request<RoleGrant & { created_user: boolean; created_membership: boolean }>("/admin/roles", {
    method: "POST",
    body: JSON.stringify(body),
  }),
  adminRevokeRole: (membershipId: string) =>
    request<{ revoked: RoleGrant }>(`/admin/roles/${membershipId}`, { method: "DELETE" }),

  classGaps: (classroomId: string) =>
    request<{ classroom_id: string; gaps: ClassGap[] }>(`/classrooms/${classroomId}/gaps`),

  classStudents: (classroomId: string) =>
    request<{ classroom_id: string; name: string; students: StudentRow[] }>(
      `/classrooms/${classroomId}/students`,
    ),

  classDigest: (classroomId: string) =>
    request<ClassDigest>(`/classrooms/${classroomId}/digest`),

  studentProfile: (studentId: string) =>
    request<StudentProfile>(`/students/${studentId}/profile`),

  studentTrajectory: (studentId: string) =>
    request<Trajectory>(`/students/${studentId}/trajectory`),

  tutorExplain: (studentId: string, competencyCode: string) =>
    request<TutorExplanation>(
      `/students/${studentId}/tutor?competency_code=${encodeURIComponent(competencyCode)}`,
    ),

  remediation: (competency_code: string, lang: string) =>
    request<RemediationPreview>("/remediation/preview", {
      method: "POST",
      body: JSON.stringify({ competency_code, lang }),
    }),

  schoolOverview: (schoolId: string) =>
    request<SchoolOverview>(`/schools/${schoolId}/overview`),

  schoolProof: (schoolId: string) =>
    request<ProofSurfaces>(`/schools/${schoolId}/proof`),

  // — Console linguiste : descente de l'arabe (Mouvement 02) —
  arCoverage: () => request<ArCoverage>("/admin/arabic/coverage"),
  arPending: () =>
    request<{ items: ArItem[]; coverage: ArCoverage }>("/admin/arabic/pending"),
  arPropose: (itemId: string) =>
    request<ArItem>(`/admin/arabic/${itemId}/propose`, { method: "POST" }),
  arValidate: (itemId: string) =>
    request<ArItem>(`/admin/arabic/${itemId}/validate`, { method: "POST" }),

  // — Back-office linguiste (persona dédié) : file de validation AR —
  linguistQueue: () => request<LinguistQueue>("/linguist/queue"),
  linguistItem: (itemId: string) => request<LinguistItem>(`/linguist/items/${itemId}`),
  linguistEditArabic: (itemId: string, content_ar: Record<string, unknown>) =>
    request<LinguistItem>(`/linguist/items/${itemId}/arabic`, {
      method: "POST",
      body: JSON.stringify({ content_ar }),
    }),
  linguistValidate: (itemId: string) =>
    request<LinguistItem>(`/linguist/items/${itemId}/validate`, { method: "POST" }),
  linguistFlag: (itemId: string, reason: string) =>
    request<LinguistItem>(`/linguist/items/${itemId}/flag`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),

  // — File de revue de la banque (refonte A4) : relecteur de contenu, super admin —
  // — Curriculums dynamiques (refonte C2/C3, écran O3) : super admin —
  competencies: () => request<{ nodes: GraphNode[] }>("/competencies"),
  opsCurricula: () => request<{ frameworks: CurriculumFrameworkRow[] }>("/ops/curricula"),
  opsCurriculaImport: (body: Record<string, unknown>) =>
    request<CurriculumFrameworkRow & { import: Record<string, number | boolean> }>("/ops/curricula", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  opsCurriculum: (id: string) => request<CurriculumDetail>(`/ops/curricula/${id}`),
  opsCurriculumSetMapping: (id: string, body: Record<string, unknown>) =>
    request<FrameworkCoverage>(`/ops/curricula/${id}/mappings`, { method: "PUT", body: JSON.stringify(body) }),
  opsCurriculumDeleteMapping: (id: string, standard_id: string, competency_id: string) =>
    request<FrameworkCoverage>(`/ops/curricula/${id}/mappings`, {
      method: "DELETE",
      body: JSON.stringify({ standard_id, competency_id }),
    }),
  opsCurriculumNoMatch: (id: string, standard_id: string, no_match: boolean) =>
    request<FrameworkCoverage>(`/ops/curricula/${id}/no-match`, {
      method: "POST",
      body: JSON.stringify({ standard_id, no_match }),
    }),
  opsCurriculumPreview: (id: string, q: { standard_id: string; alignment_type: string; confidence: string; enrich_kind?: string | null }) => {
    const params = new URLSearchParams({ standard_id: q.standard_id, alignment_type: q.alignment_type, confidence: q.confidence });
    if (q.enrich_kind) params.set("enrich_kind", q.enrich_kind);
    return request<{ preview_en: string; preview_ar: string }>(`/ops/curricula/${id}/preview?${params}`);
  },
  opsCurriculumSuggest: (id: string) => request<{ suggested: number }>(`/ops/curricula/${id}/suggest`, { method: "POST" }),
  opsCurriculumPublish: (id: string) => request<CurriculumFrameworkRow>(`/ops/curricula/${id}/publish`, { method: "POST" }),
  opsCurriculumUnpublish: (id: string) => request<CurriculumFrameworkRow>(`/ops/curricula/${id}/unpublish`, { method: "POST" }),
  opsCurriculumDelete: (id: string) => request<{ deleted: string }>(`/ops/curricula/${id}`, { method: "DELETE" }),

  opsReview: (source?: ReviewSource) =>
    request<ReviewQueue>(`/ops/review${source ? `?source=${source}` : ""}`),
  opsReviewItem: (itemId: string) => request<ReviewDetail>(`/ops/review/items/${itemId}`),
  itemTransition: (itemId: string, target: "human_reviewed" | "quarantined" | "active", reason?: string) =>
    request<ReviewDetail>(`/items/${itemId}/transition`, {
      method: "POST",
      body: JSON.stringify({ target, reason }),
    }),
  itemReject: (itemId: string, reason: string) =>
    request<{ item_id: string; rejected: boolean }>(`/items/${itemId}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  itemFlagResolve: (flagId: string, accept: boolean) =>
    request<unknown>(`/items/flags/${flagId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ accept }),
    }),
  opsTemplateQuarantine: (key: string, reason?: string) =>
    request<{ key: string; quarantined: string[] }>(`/ops/templates/${encodeURIComponent(key)}/quarantine`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  opsTemplateRegenerate: (key: string, dryRun: boolean) =>
    request<{ regenerated: { template_key: string; from_version: number; to_version: number }[]; created: string[]; unchanged: string[]; dry_run: boolean }>(
      `/ops/templates/${encodeURIComponent(key)}/regenerate?dry_run=${dryRun ? "true" : "false"}`,
      { method: "POST" },
    ),

  // — Refonte phase B : plan, check-ins, preuves, leçons —
  classroomPlan: (classroomId: string, week?: string) =>
    request<WeeklyPlan>(`/classrooms/${classroomId}/plan${week ? `?week=${week}` : ""}`),
  planAction: (actionId: string) => request<PlanAction>(`/plan-actions/${actionId}`),
  planActionMembers: (actionId: string, add: string[], remove: string[]) =>
    request<PlanAction>(`/plan-actions/${actionId}/members`, { method: "PATCH", body: JSON.stringify({ add, remove }) }),
  planActionDismiss: (actionId: string) => request<PlanAction>(`/plan-actions/${actionId}/dismiss`, { method: "POST" }),
  planActionDone: (actionId: string) =>
    request<{ action: PlanAction; recheck: CheckInInfo }>(`/plan-actions/${actionId}/done`, { method: "POST" }),
  planActionProof: (actionId: string) => request<ProofCardData>(`/plan-actions/${actionId}/proof`),
  classroomProofs: (classroomId: string, since?: string) =>
    request<ClassroomProofs>(`/classrooms/${classroomId}/proofs${since ? `?since=${since}` : ""}`),
  classroomMatrix: (classroomId: string) => request<ClassMatrix>(`/classrooms/${classroomId}/matrix`),
  openCheckin: (classroomId: string, body: { kind: "full" | "targeted"; competency_ids?: string[]; student_ids?: string[]; action_id?: string }) =>
    request<CheckInInfo>(`/classrooms/${classroomId}/checkins`, { method: "POST", body: JSON.stringify(body) }),
  classroomCheckins: (classroomId: string) =>
    request<{ classroom_id: string; checkins: CheckInInfo[] }>(`/classrooms/${classroomId}/checkins`),
  checkin: (checkinId: string) => request<CheckInInfo>(`/checkins/${checkinId}`),
  checkinProgress: (checkinId: string) => request<CheckInProgress>(`/checkins/${checkinId}/progress`),
  closeCheckin: (checkinId: string) => request<CheckInClosed>(`/checkins/${checkinId}/close`, { method: "POST" }),
  startCheckin: (checkinId: string) => request<CheckInInfo>(`/checkins/${checkinId}/start`, { method: "POST" }),
  joinCheckin: (code: string, locale: string) =>
    request<{ session_id: string; checkin_id: string; status: string; locale: string }>("/checkins/join", {
      method: "POST",
      body: JSON.stringify({ code, locale }),
    }),
  lesson: (lessonId: string) => request<Lesson>(`/lessons/${lessonId}`),
  studentUnlocks: (studentId: string) => request<UnlockHistory>(`/students/${studentId}/unlocks`),
  opsLessons: () => request<{ lessons: LessonSummary[]; coverage: LessonCoverage[] }>("/ops/lessons"),
  opsLessonCreate: (body: Record<string, unknown>) =>
    request<Lesson>("/ops/lessons", { method: "POST", body: JSON.stringify(body) }),
  opsLessonUpdate: (lessonId: string, body: Record<string, unknown>) =>
    request<Lesson>(`/ops/lessons/${lessonId}`, { method: "PUT", body: JSON.stringify(body) }),
  lessonActivate: (lessonId: string) => request<Lesson>(`/lessons/${lessonId}/activate`, { method: "POST" }),

  // — Réglages d'école : message hebdomadaire (B6 / I1) —
  adminSchools: () => request<{ schools: SchoolMailSettings[] }>("/admin/schools"),
  schoolSettingsPatch: (schoolId: string, body: { country?: string | null; plan_mail_weekday?: number | null; plan_mail_hour?: number | null; timezone?: string | null }) =>
    request<SchoolMailSettings & { school_id: string }>(`/schools/${schoolId}/settings`, { method: "PATCH", body: JSON.stringify(body) }),

  // — Session élève —
  startSession: (student_id: string) =>
    request<{ session_id: string; status: string }>("/sessions", {
      method: "POST",
      body: JSON.stringify({ student_id }),
    }),

  nextItem: (sessionId: string) => request<NextItem>(`/sessions/${sessionId}/next-item`),

  submitResponse: (sessionId: string, item_id: string, selected: string, lang: string) =>
    request<NextItem>(`/sessions/${sessionId}/responses`, {
      method: "POST",
      body: JSON.stringify({ item_id, selected, lang }),
    }),
};
