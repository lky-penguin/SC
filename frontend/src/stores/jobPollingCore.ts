//轮询器骨架抽出来共用 session / round 两个版本号是给过期回包用的
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

  //记下当下的会话版本和 owner作为回包时的判断依据
  const capture = (): PollContext => {
    const version = session;
    const owner = getOwner();
    return { isCurrent: () => session === version && getOwner() === owner };
  };

  const tick = (): Promise<void> => {
    //同一时刻只允许一个请求在飞
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
//不用手动清理，也不会因为 HMR 重复建定时器
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
