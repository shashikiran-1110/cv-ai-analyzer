import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { ReportStep } from "../components/ReportStep";
import { Skeleton } from "../components/Skeleton";
import type { Analysis } from "../types";

export function AnalysisPage() {
  const { aid = "" } = useParams();
  const q = useQuery({ queryKey: ["analysis", aid], queryFn: () => api<Analysis>(`/api/analysis/${aid}`), staleTime: Infinity });
  if (q.isLoading) return <section><h1>Loading your report…</h1><Skeleton rows={6} /></section>;
  if (q.isError || !q.data) return (
    <section className="enter"><h1>Report not found</h1>
      <div className="alert error">{(q.error as Error)?.message || "This analysis expired."}</div>
      <Link className="btn" to="/">Start a new analysis</Link></section>);
  let notes: string[] = [];
  try { notes = JSON.parse(sessionStorage.getItem(`cvm.notes.${aid}`) || "[]"); } catch { /* none */ }
  return <ReportStep key={aid} initial={q.data} notes={notes} />;
}
