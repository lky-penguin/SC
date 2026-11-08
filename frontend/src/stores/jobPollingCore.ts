export interface PollContext { isCurrent(): boolean; }

export const createJobPoller = (
  intervalMs: number,
  onTick: (context: PollContext) => Promise<void>,
  getOwner: () => string | null,
) => {
  let timer: ReturnType<typeof setInterval> | null = null;
  let session = 0;
  let round = 0;
  let pending: Promise<void> | null = null;

  const capture = (): PollContext => {
    const version = session;
    const owner = getOwner();
    return { isCurrent: () => session === version && getOwner() === owner };
  };

  const tick = (): Promise<void> => {
    if (pending) return pending;
    const context = capture();
    const version = round;
    const task = Promise.resolve()
      .then(() => onTick({ isCurrent: () => context.isCurrent() && round === version }))
      .finally(() => { if (pending === task) pending = null; });
    pending = task;
    return task;
  };

  const stop = () => {
    if (timer !== null) clearInterval(timer);
    timer = null;
    round += 1;
    pending = null;
  };

  return {
    start() {
      if (timer !== null) return;
      timer = setInterval(() => void tick(), intervalMs);
      void tick();
    },
    stop,
    tick,
    capture,
    reset() {
      stop();
      session += 1;
    },
    get active() { return timer !== null; },
  };
};

export const createStorePoller = (intervalMs: number, getOwner: () => string | null) => {
  const pollers = new WeakMap<object, ReturnType<typeof createJobPoller>>();
  return (store: { _poll(context: PollContext): Promise<void> }) => {
    let poller = pollers.get(store);
    if (!poller) {
      poller = createJobPoller(intervalMs, (context) => store._poll(context), getOwner);
      pollers.set(store, poller);
    }
    return poller;
  };
};
