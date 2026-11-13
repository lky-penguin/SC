//翻页时保住滚动位置
//分页器通常在表格底部
//用户得重新找鼠标 这里的做法是：动作前记下各层滚动容器的位置和最大可滚距离，结束后（含 DOM 更新和一次 rAF）后再换算回去
import { nextTick } from 'vue';
import { SCROLLABLE_OVERFLOW } from '@/utils/scrollChain';

const POSITION_EPSILON_PX = 0.5;
//从锚点往上找出所有纵向可滚的祖先，最后补上文档根
const scrollTargets = (anchor?: HTMLElement | null): HTMLElement[] => {
  const targets: HTMLElement[] = [];
  for (let node = anchor ?? null; node; node = node.parentElement) {
    if (SCROLLABLE_OVERFLOW.test(getComputedStyle(node).overflowY)) targets.push(node);
  }
  const root = (document.scrollingElement as HTMLElement | null) ?? document.documentElement;
  if (root && !targets.includes(root)) targets.push(root);
  return targets;
};
interface Anchor { el: HTMLElement; top: number; max: number; viewport: number; }
const capture = (anchor?: HTMLElement | null): Anchor[] => scrollTargets(anchor).map((el) => ({
  el,
  top: el.scrollTop,
  max: el.scrollHeight - el.clientHeight,
  viewport: el.clientHeight,
}));
const restore = (anchors: Anchor[]): void => {
  for (const { el, top, max, viewport } of anchors) {
    const nextMax = el.scrollHeight - el.clientHeight;
    //原来贴着底部（或离底不足一屏）的，按"距底距离"还原
    const bottomGap = max - top;
    const target = bottomGap <= viewport ? nextMax - bottomGap : top;
    const clamped = Math.max(0, Math.min(nextMax, target));
    if (Math.abs(el.scrollTop - clamped) > POSITION_EPSILON_PX) el.scrollTop = clamped;
  }
};

export const keepScroll = async (  
  action: () => unknown,
  anchor?: HTMLElement | null,
  isCurrent: () => boolean = () => true,
): Promise<void> => {
  const anchors = capture(anchor);
  try {
    await action();
  } finally {
    //摆三次：el-table 的高度是异步算出来的，第一次摆完还可能被撑开，nextTick 之后补一次，等一帧再补一次 isCurrent
    if (isCurrent()) {
      restore(anchors);
      await nextTick();
      if (isCurrent()) {
        restore(anchors);
        await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
        if (isCurrent()) restore(anchors);
      }
    }
  }
};
