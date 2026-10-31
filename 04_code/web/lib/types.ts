// Types alignés sur les payloads FastAPI (src/api/app.py + views_service.py).

export interface Me {
  user_id: string;
  roles: string[];
  schools: { id: string; name: string }[];
  classrooms: { id: string; name: string; school_id: string; grade?: number | null }[];
  child_student_ids: string[];
  own_student_id: string | null;
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
  curriculum_view: string;
  available_frameworks: string[];
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
