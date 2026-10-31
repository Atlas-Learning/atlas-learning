// Types alignés sur les payloads FastAPI (src/api/app.py + views_service.py).

export interface Me {
  user_id: string;
  roles: string[];
  schools: { id: string; name: string }[];
  classrooms: { id: string; name: string; school_id: string; grade?: number | null }[];
  // Refonte A1 : organisations lues (group_admin) ou administrées (it_admin) ;
  // couples (école, niveau) d'un dept_lead.
  organizations: { id: string; name: string }[];
  department_scopes: { school_id: string; grade: number }[];
  child_student_ids: string[];
  own_student_id: string | null;
}

// Refonte phase B — plan de la semaine, check-ins, preuves, leçons (écrans E1–E6, S1–S3).
export interface CompRef {
  competency_id: string;
  code: string;
  label_en: string;
  label_ar: string;
}
export type CellState = "mastered" | "progress" | "estimated" | "unmeasured";

export interface LessonStep {
  kind: "warmup" | "model" | "guided" | "exit";
  minutes: number;
  body_en: string;
  body_ar?: string | null;
  items?: unknown[];
}
export interface LessonSummary {
  id: string;
  key: string;
  competency_id: string;
  title_en: string;
  title_ar: string | null;
  duration_min: number;
  status: "draft" | "linguist_validated" | "active";
  origin: "atlas" | "school";
  version: number;
  arabic_complete: boolean;
  competency?: { code: string; label_en: string; label_ar: string };
}
export interface Lesson extends LessonSummary {
  steps: LessonStep[];
}
export interface LessonCoverage {
  competency_id: string;
  code: string;
  label_en: string;
  label_ar: string;
  grade: number;
  unlocks: number;
  lessons: LessonSummary[];
  best_status: string | null;
}

export interface PlanMember {
  student_id: string;
  external_ref: string | null;
  source: "atlas" | "teacher_added";
  removed_by_teacher: boolean;
  observed_error: string | null;
  root: { state: CellState; elo: number | null; confidence: number | null };
}
export interface PlanAction {
  id: string;
  plan_id: string;
  kind: "reteach" | "recheck";
  rank: number;
  status: "proposed" | "done" | "dismissed";
  confidence: "measured" | "partly_estimated";
  root_cause: CompRef;
  blocked: CompRef;
  because_en: string;
  because_ar: string;
  lesson_id: string | null;
  lesson: LessonSummary | null;
  n_members: number;
  done_at: string | null;
  dismissed_at: string | null;
  members?: PlanMember[];
}
export interface WeeklyPlan {
  id: string;
  classroom_id: string;
  week_start: string;
  status: "active" | "superseded";
  generated_at: string | null;
  source_checkin_id: string | null;
  actions: PlanAction[];
}

export interface CheckInInfo {
  id: string;
  classroom_id: string;
  kind: "full" | "targeted";
  status: "scheduled" | "open" | "closed";
  n_competencies: number;
  competency_ids: string[] | null;
  n_members: number | null;
  plan_action_id: string | null;
  opened_at: string | null;
  closed_at: string | null;
  code?: string;
}
export interface CheckInProgress {
  checkin_id: string;
  kind: "full" | "targeted";
  status: "scheduled" | "open" | "closed";
  counts: { expected: number; joined: number; in_progress: number; finished: number; absent: number };
  tiles: { state: "absent" | "in_progress" | "finished"; n_answered: number }[];
}
export interface CheckInClosed {
  checkin_id: string;
  already_closed: boolean;
  closed_sessions: number;
  plan_id: string | null;
  proof: { action_id: string; unlocked: number; unchanged: number; not_rechecked: number } | null;
  progress: CheckInProgress;
}

export interface ProofRow {
  student_id: string;
  external_ref: string | null;
  competency_code: string | null;
  before: { elo: number; confidence: number; measured: boolean };
  after: { elo: number; confidence: number; measured: boolean; ci_low: number; ci_high: number } | null;
  outcome: "unlocked" | "unchanged" | "not_rechecked";
  suggestion: { kind: "upstream_cause" | "practise_again" | "add_to_next_recheck"; competency?: CompRef | null } | null;
}
export interface ProofCardData {
  action_id: string;
  status: string;
  done_at: string | null;
  root_cause: CompRef | null;
  recheck: CheckInInfo | null;
  computed: boolean;
  header: { unlocked: number; rechecked: number; not_rechecked: number; interval_note: string };
  students: ProofRow[];
  loop_closed: boolean;
}
export interface ClassroomProofs {
  classroom_id: string;
  loops_closed: number;
  proofs: ProofCardData[];
}
export interface ClassMatrix {
  classroom_id: string;
  competencies: { code: string; label_en: string; label_ar: string; grade: number | null }[];
  students: {
    student_id: string;
    external_ref: string;
    cells: Record<string, { state: CellState; elo: number | null; confidence: number | null }>;
    n_mastered: number;
  }[];
}
export interface UnlockHistory {
  student_id: string;
  unlocks: { competency_code: string | null; label_en: string | null; label_ar: string | null; before_elo: number; after_elo: number | null; unlocked_at: string | null }[];
}

// Réglages du message hebdomadaire par école (B6, écran I1).
export interface SchoolMailSettings {
  id: string;
  name: string;
  organization_id: string | null;
  country: string | null;
  plan_mail_weekday: number | null;
  plan_mail_hour: number | null;
  timezone: string | null;
  effective: { weekday: number; hour: number; timezone: string };
}

// File de revue de la banque (refonte A4, écran O2) — /ops/review.
export type ReviewSource = "flag" | "validation" | "school" | "arabic";
export type ReviewAction =
  | "approve" | "quarantine" | "reject" | "resolve_flag" | "quarantine_template"
  | "activate" | "rehabilitate" | "regenerate";

export interface ReviewEntry {
  item_id: string;
  competency_id: string;
  competency_code: string | null;
  status: string;
  origin: "atlas_template" | "school";
  version: number;
  template_key: string | null;
  template: string | null;
  owner_school_id: string | null;
  stem_en: string | null;
  stem_ar: string | null;
  ar_validated: boolean;
  n_responses: number;
  sources: ReviewSource[];
  open_flags: number;
  flag_reasons: string[];
  flag_schools: number;
  validation_errors: string[];
  created_at: string | null;
  actions: ReviewAction[];
}

export interface ReviewGroup {
  template: string | null;
  competency_code: string | null;
  items: ReviewEntry[];
  n_items: number;
  n_active: number;
  open_flags: number;
  sources: ReviewSource[];
}

export interface ReviewQueue {
  source: ReviewSource | "all";
  counts: Record<ReviewSource | "all", number>;
  groups: ReviewGroup[];
  n_items: number;
}

export interface ReviewFlag {
  id: string;
  reason: string;
  comment: string | null;
  status: "open" | "accepted" | "rejected";
  school_id: string | null;
  created_at: string | null;
}

export interface ReviewDetail extends ReviewEntry {
  content_en: { stem?: string; options?: string[]; answer?: string; [k: string]: unknown };
  content_ar: { stem?: string; options?: string[]; answer?: string; [k: string]: unknown } | null;
  difficulty_prior: number;
  difficulty_elo: number;
  calibration_reset_at: string | null;
  provenance: Record<string, unknown>;
  flags: ReviewFlag[];
  versions: { item_id: string; version: number; status: string; deleted: boolean; n_responses: number }[];
  lifecycle: string[];
}

// Attribution d'un rôle hors roster (dept_lead, group_admin) — /admin/roles.
export interface RoleGrant {
  membership_id: string;
  user_id: string;
  email: string;
  role: "dept_lead" | "group_admin";
  organization_id: string | null;
  school_id: string | null;
  school_name: string | null;
  grades: number[];
  source: "roster" | "manual";
}

// B4 : payload `standard` ADDITIF — présent UNIQUEMENT si la vue curriculaire du
// tenant ≠ ATLAS (contrat de non-régression : jamais de champ en vue neutre).
export interface StandardRef {
  framework: string;
  code: string;
  // display_code = code affichable (CCSS/UK) ou null (MoE UAE n'a pas de code officiel :
  // on affiche le label, jamais la clé technique NUM_OPS.{band}).
  display_code: string | null;
  label_en: string;
  label_ar: string;
  alignment_type: string;
  wording_en: string;
  wording_ar: string;
}

export interface ClassGap {
  root_cause: string;
  label: string;
  root_cause_label_en: string;
  root_cause_label_ar: string;
  gap_label_en: string;
  gap_label_ar: string;
  is_self: boolean;
  student_count: number;
  diagnosis: string;
  standard?: StandardRef | null;
  standards?: StandardRef[];
}

export interface StudentRow {
  student_id: string;
  external_ref: string;
  mean_ability: number | null;
  n_measured: number;
  n_gaps: number;
}

export interface Restitution {
  ability: number | null;
  confidence: number;
  percentile: number | null;
  level: string | null;
  is_range: boolean;
  percentile_range: [number, number] | null;
  measured: boolean;
}

export interface CompetencyMastery {
  code: string;
  label_en: string;
  label_ar: string;
  grade: number | null;
  strand: string;
  ability_elo: number;
  confidence: number;
  n_direct: number;
  measured: boolean;
  mastered: boolean;
  standard?: StandardRef | null;
  standards?: StandardRef[];
}

export interface Diagnosis {
  gap: string;
  gap_label: string;
  gap_label_ar: string;
  root_cause: string;
  root_cause_label: string;
  root_cause_label_ar: string;
  is_self: boolean;
  chain: string[];
  chain_labels: string[];
  chain_labels_ar: string[];
  explanation: string;
}

export interface StudentProfile {
  student_id: string;
  external_ref: string;
  restitution: Restitution;
  competencies: CompetencyMastery[];
  diagnoses: Diagnosis[];
  n_measured: number;
  n_gaps: number;
}

export interface HomeActivity {
  item_id: string;
  answer_format: "MCQ" | "NUMERIC" | "SHORT";
  example_en: string | null;
  example_ar: string | null;
}

export interface NextStep {
  competency_code: string;
  skill_label_en: string;
  skill_label_ar: string;
  is_self: boolean;
  gap_label_en: string;
  gap_label_ar: string;
  minutes: number;
  activity: HomeActivity | null;
}

export interface Trajectory {
  student_id: string;
  restitution: Restitution;
  n_mastered: number;
  mastered: { label_en: string; label_ar: string }[];
  closing_gaps: {
    label_en: string;
    label_ar: string;
    ability_elo: number;
    confidence: number;
    progress: number;
  }[];
  next_step: NextStep | null;
}

export interface EmergingGap {
  root_cause: string;
  root_cause_label_en: string;
  root_cause_label_ar: string;
  gap_label_en: string;
  gap_label_ar: string;
  is_self: boolean;
  student_count: number;
  standard?: StandardRef | null;
  standards?: StandardRef[];
}

export interface ClassDigest {
  classroom_id: string;
  window_days: number;
  since: string;
  n_students: number;
  n_active_students: number;
  n_responses: number;
  emerging_gaps: EmergingGap[];
  top_priority: ClassGap | null;
}

export interface SchoolOverview {
  school_id: string;
  n_students: number;
  competencies: {
    code: string;
    label: string;
    mean_ability: number;
    mastery_rate: number;
    n_measured: number;
  }[];
  classes: {
    classroom_id: string;
    name: string;
    n_students: number;
    mean_ability: number | null;
  }[];
}

export interface ArCoverage {
  total_items: number;
  with_ar: number;
  ar_validated: number;
  active: number;
  math_preserved: number;
  pct_validated: number;
}

export interface ArItem {
  item_id: string;
  competency_id: string;
  status: string;
  answer_format: "MCQ" | "NUMERIC" | "SHORT";
  content_en: { stem?: string; options?: string[]; [k: string]: unknown };
  content_ar: { stem?: string; options?: string[]; [k: string]: unknown } | null;
  ar_validated: boolean;
  math_preserved: boolean;
}

// Item de la file du back-office linguiste (persona dédié). Comme ArItem, plus le flag
// de fidélité math persisté (ar_math_broken) et la provenance utile à la revue.
export interface LinguistItem {
  item_id: string;
  competency_id: string;
  status: string;
  answer_format: "MCQ" | "NUMERIC" | "SHORT";
  content_en: { stem?: string; options?: string[]; answer?: string; [k: string]: unknown };
  content_ar: { stem?: string; options?: string[]; answer?: string; [k: string]: unknown } | null;
  ar_validated: boolean;
  ar_math_broken: boolean;
  math_preserved: boolean;
  provenance: {
    ar_proposed_by?: string;
    ar_validated_by?: string;
    ar_math_broken?: boolean;
    flag_reason?: string;
    flagged_by?: string;
  };
}

export interface LinguistQueue {
  items: LinguistItem[];
  remaining: number;
  coverage: ArCoverage;
}

export interface TutorExplanation {
  available: boolean;
  competency_code?: string;
  is_self?: boolean;
  headline_en?: string;
  headline_ar?: string;
  steps?: { from_code: string; to_code: string; reason_en: string; reason_ar: string }[];
  why_en?: string;
  why_ar?: string;
}

export interface ProofSurfaces {
  school_id: string;
  cohort: {
    window_days: number;
    before: number | null;
    after: number | null;
    n_before: number;
    n_after: number;
    delta: number | null;
  };
  gains: {
    competency_code: string;
    label_en: string;
    label_ar: string;
    before: number;
    after: number;
    delta: number;
    n_before: number;
    n_after: number;
  }[];
  trajectory: { level: string; n_students: number }[];
  n_students_measured: number;
  n_mastered_skills: number;
  n_measured_skills: number;
  // B5 (D-B5) : section ADDITIVE du rapport — absente en vue ATLAS.
  curriculum_coverage?: CurriculumCoverage;
}

// « k/n compétences alignées sur S maîtrisées » ; covered = toutes les EXACT
// maîtrisées (rapport école UNIQUEMENT, jamais au niveau élève — règle B5).
export interface CurriculumCoverage {
  framework: string;
  // MoE UAE : pas de notion de « couvert » (aucun mapping EXACT) → shows_covered=false,
  // le rapport n'affiche pas de colonne verdict (une colonne toujours fausse = bug déguisé).
  shows_covered: boolean;
  coverage_threshold: number;
  standards: {
    code: string;
    display_code: string | null;
    label: string;
    label_ar: string;
    mastered_count: number;
    total: number;
    covered: boolean | null;
  }[];
}

export interface CurriculumSettings {
  organization: { id: string; name: string };
  curriculum_view: string;            // ce que les écoles voient (un framework dépublié → "ATLAS")
  configured_view?: string;           // refonte C2 : le choix enregistré, même non publié
  configured_status?: string | null;  // draft | published
  available_frameworks: string[];
  // Refonte C1 : les frameworks viennent de la table (noms EN/AR) ; ATLAS = vue neutre.
  frameworks?: { key: string; name_en: string; name_ar: string; country?: string | null }[];
}

export interface RemediationPreview {
  available: boolean;
  competency_code: string;
  competency_label_en?: string;
  competency_label_ar?: string;
  item_id?: string;
  answer_format?: "MCQ" | "NUMERIC" | "SHORT";
  content?: { stem?: string; options?: string[]; [k: string]: unknown };
}

export interface ItemContent {
  stem?: string;
  options?: string[];
  [k: string]: unknown;
}

export interface NextItem {
  done: boolean;
  reason?: string;
  session_id?: string;
  competency_id?: string;
  item_id?: string;
  answer_format?: "MCQ" | "NUMERIC" | "SHORT";
  content_en?: ItemContent | null;
  content_ar?: ItemContent | null;
  was_correct?: boolean; // présent seulement après soumission d'une réponse
}
