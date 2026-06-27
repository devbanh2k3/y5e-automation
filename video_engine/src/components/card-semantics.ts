export type HeaderStat = {
  label: string;
  value: string;
};

export const getHeaderStat = (header: string): HeaderStat => {
  const normalized = header.trim();
  const isRankingHeader = /^TOP\s+\d+$/i.test(normalized);
  return {
    label: isRankingHeader ? "RANK" : "TYPE",
    value: isRankingHeader ? normalized.replace(/^TOP\s*/i, "#") : normalized,
  };
};
