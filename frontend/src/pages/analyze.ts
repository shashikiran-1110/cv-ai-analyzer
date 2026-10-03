import { api } from "../api";
import type { AiSettings } from "../ai";
import { aiHeaders } from "../api";
import type { Analysis } from "../types";
import type { ResumeState } from "../components/ResumeCard";
import type { Options } from "../state/setup";

/** POST /api/analyze using the stored resume id (no re-upload, works after a page reload). */
export async function startAnalysis(searchId: string, jobIds: string[] | null, resume: ResumeState, opts: Options,
                                    ai: { usable: boolean; settings: AiSettings }): Promise<Analysis> {
  const aiOn = opts.wantAi && ai.usable;
  const fd = new FormData();
  fd.append("search_id", searchId);
  if (resume.resumeId) fd.append("resume_id", resume.resumeId);
  else if (resume.mode === "pdf" && resume.file) fd.append("resume", resume.file);
  else fd.append("resume_text", resume.text);
  fd.append("threshold", String(opts.threshold));
  fd.append("use_ai", aiOn ? "true" : "false");
  if (jobIds) fd.append("job_ids", JSON.stringify(jobIds));
  fd.append("extra_skills", JSON.stringify(resume.extra));
  return api<Analysis>("/api/analyze", { method: "POST", body: fd, headers: aiOn ? aiHeaders(ai.settings) : {} });
}
