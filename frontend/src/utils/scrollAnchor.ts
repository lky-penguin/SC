/** Keep the pager under the pointer when a page swap changes document height. */
import { nextTick } from 'vue';
import { SCROLLABLE_OVERFLOW } from '@/utils/scrollChain';

const POSITION_EPSILON_PX = 0.5;

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
