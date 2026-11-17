// 조문 norm → 표시형. 백엔드 law_rag_tool.article_display와 같은 규칙 (#104):
// "17" → "제17조", "14의2" → "제14조의2", "별표3#2"(별표 청크) → "별표 3"
export const articleLabel = (norm: string): string => {
  if (norm.startsWith("별표")) return norm.split("#")[0].replace("별표", "별표 ");
  const [n, b] = norm.split("의");
  return b ? `제${n}조의${b}` : `제${n}조`;
};
