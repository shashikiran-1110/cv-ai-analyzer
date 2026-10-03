export type Provider = "openai" | "anthropic";

export interface SearchQuery {
  title: string; location: string; count: number; time_range: string; hours: number | null;
  experience: string[]; job_types: string[]; workplace: string[]; sort: string;
}
export interface SearchParams {
  title: string; location: string; count: number; time_range: string; custom_hours?: number;
  experience: string[]; job_types: string[]; workplace: string[]; sort: string;
}
export interface JobSummary {
  id: string; title: string; company: string; location: string; url: string; posted: string;
  seniority: string; employment_type: string; description_missing: boolean; description_chars: number;
}
export interface SearchStatus {
  status: "running" | "done" | "error"; stage: "searching" | "details"; done: number; total: number;
  error: string | null; query: SearchQuery; jobs?: JobSummary[];
}
export interface ScoredJob {
  id: string; title: string; company: string; location: string; url: string; posted: string; score: number;
  components: { skills: number; role: number; experience: number };
  matched_skills: string[]; missing_skills: string[]; required_missing: string[];
  matched_keywords: string[]; missing_keywords: string[];
  required_years: number | null; required_years_inferred: boolean; confidence: "high" | "low";
}
export interface SkillStat { skill: string; category: string; jobs: number; pct: number }
export interface Summary {
  job_count: number; avg_score: number; qualifying: number; threshold: number; distribution: number[];
  resume_skills: string[]; resume_years: number; skill_gaps: SkillStat[]; skill_strengths: SkillStat[];
  unused_skills: string[];
}
export interface LearnItem { skill: string; why: string; how?: string; jobs?: number | null }
export interface Insights {
  source: string; summary: string; strengths: string[]; improvements: string[];
  skills_to_learn: LearnItem[]; ai_error?: string;
}
export interface Analysis {
  analysis_id: string; extra_skills: string[]; unknown_skills: string[]; query: SearchQuery;
  summary: Summary; jobs: ScoredJob[]; insights: Insights;
}
export interface JobDetail { id: string; title: string; company: string; location: string; url: string; description: string }
export interface AppConfig { max_jobs: number; default_threshold: number; server_ai: Provider | null; default_models: Record<Provider, string> }
export interface VerifyResult { ok: boolean; warning?: boolean; message: string }
export interface SkillInfo { name: string; category: string }
export interface ChatMsg { role: "user" | "assistant"; content: string }
