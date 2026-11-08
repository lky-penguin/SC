export const messageOf = (err: unknown, fallback: string): string =>
  err instanceof Error && err.message ? err.message : fallback;

export const createIsTerminal = <T extends { status: string }>(terminalStatuses: readonly string[]) =>
  (job: T): boolean => terminalStatuses.includes(job.status);

export const trimFinishedJobs = <T extends { startedAt: number }>(
  jobs: T[],
  isTerminal: (job: T) => boolean,
  keyOf: (job: T) => string,
  maxFinished: number,
): T[] => {
  const finished = jobs.filter(isTerminal);
  if (finished.length <= maxFinished) return jobs;
  const drop = new Set(finished.sort((a, b) => a.startedAt - b.startedAt)
    .slice(0, finished.length - maxFinished).map(keyOf));
  return jobs.filter((job) => !drop.has(keyOf(job)));
};
