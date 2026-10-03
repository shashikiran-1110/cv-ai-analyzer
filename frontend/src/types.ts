export type Provider = "openai" | "anthropic";

export interface SearchQuery {
  title: string; location: string; count: number; time_range: string; hours: number | null;
  experience: string[]; job_types: string[]; workplace: string[]; sort: string; sources?: string[];
}
export interface SearchParams {
  title: string; location: string; count: number; time_range: string; custom_hours?: number;
  experience: string[]; job_types: string[]; workplace: string[]; sort: string; strict: boolean;
  alt_titles?: string[]; exclude_titles?: string[];
}
export interface SearchPlan {
  title: string; alt_titles: string[]; exclude_titles: string[]; seniority: string[]; location: string; workplace: string[];
  keywords: string[]; note: string; source: string; dropped_titles?: string[]; ai_error?: string;
}
export interface SourceInfo { id: string; name: string; kind: string; remote_only: boolean; needs: string; note: string; host: string }
export interface SourceStat {
  id: string; name: string; status: "running" | "done" | "error"; fetched: number; kept: number; selected?: number;
  message: string; kind?: string; progress?: { stage: string; done: number; total: number } | null;
}
export interface JobSummary {
  id: string; title: string; company: string; location: string; url: string; posted: string;
  seniority: string; employment_type: string; description_missing: boolean; description_chars: number;
  source: string; sources: string[]; remote: boolean | null; salary: string;
}
export interface SearchStatus {
  status: "running" | "done" | "error"; stage: string; done: number; total: number;
  error: string | null; query: SearchQuery; jobs?: JobSummary[]; warnings?: string[]; sources?: SourceStat[]; cached?: boolean;
  linkedin?: { stage: string; done: number; total: number } | null;
}
export interface ReqCheck {
  id: string; text: string; preferred: boolean; coverage: number; missing: string[]; status: "met" | "partial" | "missing";
  how?: string; via?: string[]; evidence?: string;
}
export interface Gate { type: string; label: string; need: string; text: string; status: "pass" | "fail" | "unknown"; reason: string }
export interface DeepReq {
  id: string; requirement: string; importance: "must" | "nice"; preferred: boolean; coverage: number;
  det_status: "met" | "partial" | "missing" | null; ai_status: "met" | "partial" | "missing" | "not assessed";
  final_status: "met" | "partial" | "missing"; source: "ai" | "rules"; verified: boolean;
  evidence: string; claimed_evidence: string; flag: string; note: string; disagree: boolean;
}
export interface DeepResult {
  job_id: string; mode: "fixed" | "open"; verdict: string; summary: string; det_score: number; final_score: number;
  requirements_component: number; verified: number; assessed: number; unverified_claims: number; disagreements: number;
  requirements: DeepReq[]; provider: string; model: string;
}
export interface ScoredJob {
  id: string; title: string; company: string; location: string; url: string; posted: string; score: number;
  score_det?: number; source: string; sources: string[]; salary: string; remote: boolean | null;
  components: { skills: number; requirements: number; role: number; experience: number; semantic: number };
  matched_skills: string[]; missing_skills: string[]; required_missing: string[];
  matched_keywords: string[]; missing_keywords: string[];
  requirements: ReqCheck[]; requirements_met: number; blockers: string[]; education_required: string | null; negated_skills: string[];
  required_years: number | null; required_years_inferred: boolean; confidence: "high" | "low"; deep?: DeepResult;
  gates?: Gate[]; gates_failed?: string[]; related_skills?: { skill: string; via: string; credit: number; how: string }[];
}
export interface SkillStat { skill: string; category: string; jobs: number; pct: number }
export interface Summary {
  job_count: number; avg_score: number; qualifying: number; threshold: number; distribution: number[];
  resume_skills: string[]; resume_years: number; resume_education: string | null; skill_gaps: SkillStat[];
  skill_strengths: SkillStat[]; unused_skills: string[]; common_blockers: { text: string; jobs: number }[];
  by_source: Record<string, number>;
  score_qualifying?: number; gate_failed?: number; gate_breakdown?: Record<string, number>; gate_unknown?: Record<string, number>;
}
export interface LearnItem { skill: string; why: string; how?: string; jobs?: number | null }
export interface Insights {
  source: string; summary: string; strengths: string[]; improvements: string[];
  skills_to_learn: LearnItem[]; ai_error?: string;
}
export interface Analysis {
  analysis_id: string; extra_skills: string[]; unknown_skills: string[]; query: SearchQuery;
  summary: Summary; jobs: ScoredJob[]; insights: Insights & { pending?: boolean };
  insights_run_id?: string | null; resume_id?: string; search_id?: string;
}
export interface JobDetail { id: string; title: string; company: string; location: string; url: string; description: string }
export interface AppConfig { max_jobs: number; default_threshold: number; server_ai: Provider | null; default_models: Record<Provider, string> }
export interface VerifyResult { ok: boolean; warning?: boolean; message: string }
export interface SkillInfo { name: string; category: string }
export interface ChatMsg { role: "user" | "assistant"; content: string }
export interface ExperienceSpan { start: string; end: string; months: number; line: string }
export interface ResumePreview {
  resume_id: string; chars: number; words: number; years: number; skills: string[]; education: string | null; headline: string;
  experience: { months: number; years: number; precision: string; method: string; explicit_years: number; spans: ExperienceSpan[] };
}
export interface CheckResult { name: string; ok: boolean; message: string; kind?: string }
export interface Diagnosis { api: CheckResult; checks: Record<string, CheckResult>; ai_key: VerifyResult }
export interface ProfileBullet { id: string; text: string; skills: string[]; metrics?: string[] }
export interface ProfileRole {
  id: string; title: string; company: string; start: string; end: string; months: number;
  date_precision: string; bullets: ProfileBullet[]; ignore?: boolean;
}
export interface ProfileSkill { name: string; evidence: string[]; months_used: number; last_used: string; source: string; strength: string; category: string }
export interface StructuredProfile {
  parser_version: number; headline: string; roles: ProfileRole[]; skills: ProfileSkill[]; education_level: string | null;
  education: { text: string; degree_level: string | null; institution: string; field: string; start: string; end: string }[];
  experience_months: { total: number; explicit_years: number }; parse: { warnings: string[]; confidence: number };
}
export interface RoleFix { title?: string; company?: string; start?: string; end?: string; ignore?: boolean }
export interface Eligibility {
  work_countries?: string[]; needs_sponsorship?: boolean; clearance?: string; licenses?: string[]; languages?: string[]; relocate?: boolean;
}
export interface Corrections {
  roles?: Record<string, RoleFix>; skills_add?: string[]; skills_remove?: string[];
  degree?: "" | "Bachelor's" | "Master's" | "PhD"; years_override?: number; eligibility?: Eligibility;
}
export interface ProfileView {
  resume_id: string; parsed: StructuredProfile; profile: StructuredProfile; corrections: Corrections;
  formatting: { label: string; ok: boolean; detail: string }[];
}
export interface Spend { calls: number; cost_usd: number; input_tokens: number; output_tokens: number; cached_tokens: number; result_cache_hits: number; cost_known: boolean }
export interface DeepEstimate { estimate_usd: number | null; calls: number; model?: string; message: string }
export interface TailorEdit {
  id?: string; bullet_id: string; original: string; new_text: string; rationale?: string; requirement_ids?: string[];
  violations: string[]; ok?: boolean; role?: string;
}
export interface Projection { score_before: number; score_after: number; changed: { requirement: string; before: string; after: string }[] }
export interface AgentStep { step: number; kind: string; tool?: string; tools?: string[]; text?: string; input?: string; output?: string; error?: boolean; ms?: number }
export interface AgentRun {
  id: string; kind: string; aid: string; job_id: string; status: "running" | "needs_input" | "done" | "limit" | "error";
  trace: AgentStep[]; edits: TailorEdit[]; projection?: Projection; question?: string; final?: string; error?: string;
  user_facts?: string;
}
export interface PracticeQuestion { id: string; question: string; requirement_id: string; focus: "gap" | "strength" | "general"; what_good_looks_like: string }
export interface PracticeFeedback {
  scores: { structure: number; specificity: number; relevance: number }; strengths: string[]; improvements: string[];
  stronger_answer: string; violations: string[];
}
export interface PracticeEntry { question_id: string; question: string; answer: string; feedback: PracticeFeedback; at: number }
export interface PracticeHistory { questions: PracticeQuestion[]; answers: PracticeEntry[] }
