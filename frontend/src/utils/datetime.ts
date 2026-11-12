//不要直接 new Date ，否则会按浏览器本地时区解析
//拆成两个入口：parseBeijingNaive 补 +08:00，parseInstant 补 Z
const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;
const HAS_ZONE = /[zZ]|[+-]\d{2}:?\d{2}$/;
const pad = (n: number): string => String(n).padStart(2, '0');

const parseWithZone = (value: string | null | undefined, fallbackSuffix: string): number | null => {
  if (!value) return null;
  const text = String(value).trim().replace(' ', 'T');
  if (!text) return null;
  const parsed = new Date(HAS_ZONE.test(text) ? text : `${text}${fallbackSuffix}`).getTime();
  return Number.isFinite(parsed) ? parsed : null;
};

export const parseBeijingNaive = (value?: string | null): number | null => parseWithZone(value, '+08:00');
export const parseInstant = (value?: string | null): number | null => parseWithZone(value, 'Z');
export const toMillis = (createdAt?: number): number =>
  typeof createdAt === 'number' && Number.isFinite(createdAt) && createdAt > 0 ? createdAt * 1000 : Date.now();
export const toBeijingParts = (ms: number) => {
  const date = new Date(ms + BEIJING_OFFSET_MS);
  return {
    year: date.getUTCFullYear(),
    month: date.getUTCMonth() + 1,
    day: date.getUTCDate(),
    hour: date.getUTCHours(),
    minute: date.getUTCMinutes(),
    second: date.getUTCSeconds(),
  };
};
export const formatBeijingDateTime = (ms: number): string => {
  const p = toBeijingParts(ms);
  return `${p.year}-${pad(p.month)}-${pad(p.day)} ${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
};
//只留月日时分
export const formatBeijingShort = (ms: number): string => {
  const p = toBeijingParts(ms);
  return `${pad(p.month)}-${pad(p.day)} ${pad(p.hour)}:${pad(p.minute)}`;
};
