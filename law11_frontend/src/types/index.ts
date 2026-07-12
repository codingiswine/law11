export interface LawSource {
  law_name: string;
  article_number: string;
  score: number | null;
  rank: number;
}

export interface Message {
  role: string;
  content: string;
  messageId?: number;
  feedback?: 1 | -1 | null;
  sources?: LawSource[];
}

export interface LawReference {
  lawName: string;
  articleNumber: string;
  display: string;
}

export interface LawArticle {
  law_name: string;
  article_number: string;
  law_name_norm: string;
  article_number_norm: string;
  text: string;
  enforcement_date: string | null;
}

export interface LawContentResponse {
  law_name: string;
  articles: LawArticle[];
}

export interface SessionSummary {
  session_id: string;
  title: string;        // 세션의 첫 번째 user 메시지
  created_at: string;
}
