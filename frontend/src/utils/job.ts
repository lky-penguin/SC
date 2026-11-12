//轮询和任务列表共用的小工具  
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
  //只裁已结束的，正在训练的任务不参与淘汰
  const finished = jobs.filter(isTerminal);
  if (finished.length <= maxFinished) return jobs;   
  //按开始时间升序，先扔最老的那批
  const drop = new Set(finished.sort((a, b) => a.startedAt - b.startedAt)
    .slice(0, finished.length - maxFinished).map(keyOf));
  return jobs.filter((job) => !drop.has(keyOf(job)));
};
