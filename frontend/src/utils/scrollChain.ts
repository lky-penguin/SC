//嵌套表格的滚轮穿透
//效果就是"先滚页面，页面到底了才开始滚表格"
export const SCROLLABLE_OVERFLOW = /^(auto|scroll|overlay)$/;
const SCROLL_EPSILON_PX = 1;
const LINE_HEIGHT_PX = 16;
const INNER_SCROLLER_SELECTOR = '.el-scrollbar__wrap, .el-table__body-wrapper';
const isScrollableY = (el: HTMLElement): boolean =>
  SCROLLABLE_OVERFLOW.test(getComputedStyle(el).overflowY) && el.scrollHeight - el.clientHeight > SCROLL_EPSILON_PX;
const normalizeDelta = (event: WheelEvent, pageSize: number): number => {
  if (event.deltaMode === 1) return event.deltaY * LINE_HEIGHT_PX;
  if (event.deltaMode === 2) return event.deltaY * pageSize;
  return event.deltaY;
};

//从近到远逐层吃掉位移
const consumeOuterScroll = (start: HTMLElement, delta: number): number => {
  const chain: HTMLElement[] = [];
  for (let node = start.parentElement; node && node !== document.body; node = node.parentElement) {
    if (isScrollableY(node)) chain.push(node);
  }
  const root = (document.scrollingElement as HTMLElement | null) ?? document.documentElement;
  if (root) chain.push(root);
  let rest = delta;
  for (const el of chain) {
    if (rest === 0) break;
    const max = el.scrollHeight - el.clientHeight;
    if (max <= SCROLL_EPSILON_PX) continue;
    //夹在 [0, max] 里，减出来的差值才是真正生效的位移
    const target = Math.min(Math.max(el.scrollTop + rest, 0), max);
    const applied = target - el.scrollTop;
    if (applied === 0) continue;
    el.scrollTop = target;
    rest -= applied;
  }
  return rest;
};
//先问鼠标底下是谁；elementFromPoint 拿不到（比如指针在 iframe 上）再退回 el-table 的标准类名
const findInnerScroller = (wrap: HTMLElement, event: WheelEvent): HTMLElement | null => {
  const hit = document.elementFromPoint(event.clientX, event.clientY);
  for (let node = hit instanceof HTMLElement ? hit : null; node && node !== wrap; node = node.parentElement) {
    if (isScrollableY(node)) return node;
  }
  for (const candidate of wrap.querySelectorAll<HTMLElement>(INNER_SCROLLER_SELECTOR)) {
    if (isScrollableY(candidate)) return candidate;
  }
  return null;
};

//绑在包裹容器上，返回解绑函数
export const attachOuterFirstWheel = (wrap: HTMLElement): (() => void) => {
  const onWheel = (event: WheelEvent) => {
    //按着 Ctrl 是缩放、Shift 是横向滚、往上滚保持原生行为
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.deltaY <= 0) return;
    const inner = findInnerScroller(wrap, event);
    if (!inner) return;
    const innerMax = inner.scrollHeight - inner.clientHeight;
    if (innerMax <= SCROLL_EPSILON_PX) return;
    const delta = normalizeDelta(event, inner.clientHeight);
    if (delta === 0) return;
    const rest = consumeOuterScroll(wrap, delta);
    //外层已经吃过了，必须 preventDefault  
    event.preventDefault();
    if (rest !== 0) inner.scrollTop = Math.min(Math.max(inner.scrollTop + rest, 0), innerMax);
  };
  wrap.addEventListener('wheel', onWheel, { passive: false });
  return () => wrap.removeEventListener('wheel', onWheel);
};
