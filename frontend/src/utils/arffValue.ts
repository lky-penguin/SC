//ARFF 里的枚举值自带一层引号（'low'、"high"），下拉框是裸文本
export const stripArffQuotes = (value: unknown): string => {
  const text = String(value ?? '');
  const first = text[0];
  //只剥成对的首尾引号
  if (text.length >= 2 && first === text.at(-1) && (first === "'" || first === '"')) {
    return text.slice(1, -1);
  }
  return text;
};
