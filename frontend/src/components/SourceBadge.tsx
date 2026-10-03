const NAMES: Record<string, string> = {
  linkedin: "LinkedIn", remotive: "Remotive", remoteok: "RemoteOK", arbeitnow: "Arbeitnow", jobicy: "Jobicy",
  himalayas: "Himalayas", themuse: "The Muse", greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby",
  adzuna: "Adzuna", url: "Link", manual: "Pasted", sample: "Sample",
};
export const sourceName = (s: string) => NAMES[s] ?? s;
export function SourceBadges({ sources }: { sources: string[] }) {
  return <>{sources.filter(Boolean).map((s) => <span key={s} className={`src-badge s-${s}`}>{sourceName(s)}</span>)}</>;
}
