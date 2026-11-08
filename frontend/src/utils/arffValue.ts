/** Remove only the outer pair of ARFF enum quotes; option values still use the original text. */
export const stripArffQuotes = (value: unknown): string => {
  const text = String(value ?? '');
  const first = text[0];
  if (text.length >= 2 && first === text.at(-1) && (first === "'" || first === '"')) {
    return text.slice(1, -1);
  }
  return text;
};
