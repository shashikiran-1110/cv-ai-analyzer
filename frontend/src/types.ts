export type Provider = "openai" | "anthropic";

export interface SearchQuery {
  title: string; location: string; count: number; time_range: string; hours: number | null;
  experience: string[]; job_types: string[]; workplace: string[]; sort: string; sources?: string[];
}
export interface SearchParams {
  title: string; location: string; count: number; time_range: string; custom_hours?: number;
  experience: string[]; job_types: string[]; workplace: string[]; sort: string; strict: boolean;
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
export interface ReqCheck { id: string; text: string; preferred: boolean; coverage: number; missing: string[]; status: "met" | "partial" | "missing" }
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
}
export interface SkillStat { skill: string; category: string; jobs: number; pct: number }
export interface Summary {
  job_count: number; avg_score: number; qualifying: number; threshold: number; distribution: number[];
  resume_skills: string[]; resume_years: number; resume_education: string | null; skill_gaps: SkillStat[];
  skill_strengths: SkillStat[]; unused_skills: string[]; common_blockers: { text: string; jobs: number }[];
  by_source: Record<string, number>;
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
