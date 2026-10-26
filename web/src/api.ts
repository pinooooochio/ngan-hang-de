// Gọi API của máy chủ (FastAPI)

export type Level = "NB" | "TH" | "VD" | "VDC";
export type QType = "mcq" | "tf" | "short" | "essay";
export type Status = "draft" | "approved";

export interface ChoiceData {
  content: string;
  correct: boolean;
  pinned: boolean;
}

export interface TagRef {
  path: string;
  names: string[];
}

export interface QuestionSummary {
  code: string;
  type: QType;
  level: Level | null;
  status: Status;
  stem: string;
  tags: TagRef[];
  updated_at: string | null;
}

export interface Question extends QuestionSummary {
  choices: ChoiceData[];
  short_answer: string | null;
  solution: string;
  source: string | null;
  version: number;
  ex_source: string;
}

export interface Parsed {
  line: number;
  type: QType;
  level: Level | null;
  code: string | null;
  tags: string[][];
  stem: string;
  choices: ChoiceData[];
  short_answer: string | null;
  solution: string;
  errors: string[];
  warnings: string[];
}

export interface ImportPreviewItem extends Parsed {
  index: number;
  state: "new" | "duplicate" | "error";
  duplicate_of: string | null;
}

export interface TagNode {
  path: string;
  name: string;
  depth: number;
  count: number;
  names: string[];
}

export interface PickRow {
  tag?: string;
  level?: Level;
  count: number;
}

export interface SectionSpec {
  name: string;
  type: QType;
  points?: number;
  pick: PickRow[];
  ids: string[];
}

export interface ExamSpec {
  title: string;
  date?: string;
  duration?: number;
  variants: number;
  first_code: number;
  seed?: number;
  sections: SectionSpec[];
}

export type BuildState = "pending" | "running" | "done" | "failed";

export interface ExamFile {
  name: string;
  kind: "de" | "loigiai" | "dapan";
  variant_code: string | null;
  status: BuildState;
  cached: boolean;
  error: string | null;
  error_question: string | null;
  url: string | null;
}

export interface VariantQuestion {
  code: string;
  type: QType;
  level: Level | null;
  stem: string;
  choices: { content: string; correct: boolean }[];
  short_answer: string | null;
  solution: string;
}

export interface ExamSummary {
  id: number;
  title: string;
  date: string | null;
  duration: number | null;
  created_at: string;
  n_variants: number;
  n_questions: number;
  builds: Record<BuildState, number>;
}

export interface ExamDetail extends ExamSummary {
  config: Record<string, unknown>;
  variants: {
    code: string;
    answer_key: { sections: string[][] };
    data: { sections: { name: string; type: QType; points: number | null; questions: VariantQuestion[] }[] };
  }[];
  files: ExamFile[];
}

export type Answer = number | (boolean | null)[] | string | null;

export interface AttemptQuestion {
  code: string;
  type: QType;
  level: Level | null;
  stem: string;
  choices: { content: string; correct?: boolean }[];
  short_answer: string | null;
  solution: string;
}

export interface AttemptSummary {
  id: number;
  kind: "exam" | "quick";
  title: string;
  exam_id: number | null;
  variant_code: string | null;
  duration: number | null;
  started_at: string;
  deadline: string | null;
  submitted_at: string | null;
  late: boolean;
  score: number | null;
  max_score: number | null;
  n_questions: number;
}

export interface AttemptResult {
  points: number;
  max_points: number;
  correct: boolean | null;
}

export interface AttemptDetail extends AttemptSummary {
  data: { title: string; sections: { name: string; type: QType; points: number | null; questions: AttemptQuestion[] }[] };
  answers: Record<string, Answer>;
  results: Record<string, AttemptResult> | null;
  server_time: string;
}

export interface QuickSpec {
  title?: string;
  tag?: string;
  level?: Level;
  mcq: number;
  tf: number;
  short: number;
  essay: number;
  duration?: number;
}

export interface StatBucket {
  n: number;
  right: number;
  points: number;
  max_points: number;
  ratio: number | null;
}

export interface PracticeStats {
  attempts: number;
  by_level: Record<string, StatBucket>;
  by_tag: (StatBucket & { path: string; names: string[]; depth: number })[];
}

export const LEVELS: { value: Level; label: string }[] = [
  { value: "NB", label: "Nhận biết" },
  { value: "TH", label: "Thông hiểu" },
  { value: "VD", label: "Vận dụng" },
  { value: "VDC", label: "Vận dụng cao" },
];

export const TYPES: { value: QType; label: string }[] = [
  { value: "mcq", label: "Trắc nghiệm" },
  { value: "tf", label: "Đúng/sai" },
  { value: "short", label: "Trả lời ngắn" },
  { value: "essay", label: "Tự luận" },
];

export const levelLabel = (l: Level | null) => LEVELS.find((x) => x.value === l)?.label ?? "Chưa có mức độ";
export const typeLabel = (t: QType) => TYPES.find((x) => x.value === t)?.label ?? t;

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (data.detail) msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* giữ thông báo mặc định */
    }
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.blob()) as Promise<T>;
}

export const api = {
  listQuestions: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
    return request<{ total: number; items: QuestionSummary[] }>("GET", `/api/questions?${qs}`);
  },
  getQuestion: (code: string) => request<Question>("GET", `/api/questions/${encodeURIComponent(code)}`),
  createQuestion: (source: string, status?: Status) => request<Question>("POST", "/api/questions", { source, status }),
  updateQuestion: (code: string, source: string, status?: Status) =>
    request<Question>("PUT", `/api/questions/${encodeURIComponent(code)}`, { source, status }),
  deleteQuestion: (code: string) => request<void>("DELETE", `/api/questions/${encodeURIComponent(code)}`),
  bulk: (body: { codes: string[]; add_tag?: string; level?: Level; status?: Status }) =>
    request<{ updated: number }>("POST", "/api/questions/bulk", body),
  template: () => request<{ source: string }>("GET", "/api/template"),
  parse: (source: string) => request<Parsed[]>("POST", "/api/parse", { source }),
  tags: () => request<TagNode[]>("GET", "/api/tags"),
  stats: () => request<{ total: number; by_level: Record<string, number>; by_status: Record<string, number> }>("GET", "/api/stats"),
  importPreview: (source: string) => request<ImportPreviewItem[]>("POST", "/api/import/preview", { source }),
  importCommit: (body: {
    source: string;
    filename?: string;
    only?: number[];
    extra_tag?: string;
    default_level?: Level;
    status?: Status;
  }) => request<{ added: string[]; duplicates: number; failed: number }>("POST", "/api/import/commit", body),
  previewPdf: (source: string) => request<Blob>("POST", "/api/preview/pdf", { source }),
  availability: (sections: SectionSpec[]) =>
    request<{ sections: { rows: number[]; problems: string[] }[] }>("POST", "/api/exams/availability", { sections }),
  listExams: () => request<ExamSummary[]>("GET", "/api/exams"),
  createExam: (spec: ExamSpec) => request<ExamDetail>("POST", "/api/exams", spec),
  getExam: (id: number) => request<ExamDetail>("GET", `/api/exams/${id}`),
  rebuildExam: (id: number) => request<ExamDetail>("POST", `/api/exams/${id}/rebuild`),
  deleteExam: (id: number) => request<void>("DELETE", `/api/exams/${id}`),
  startAttempt: (body: { exam_id?: number; variant?: string; timed?: boolean; quick?: QuickSpec; retry_of?: number }) =>
    request<AttemptDetail>("POST", "/api/attempts", body),
  listAttempts: (examId?: number) => request<AttemptSummary[]>("GET", `/api/attempts${examId ? `?exam_id=${examId}` : ""}`),
  attemptStats: () => request<PracticeStats>("GET", "/api/attempts/stats"),
  getAttempt: (id: number) => request<AttemptDetail>("GET", `/api/attempts/${id}`),
  saveAnswers: (id: number, answers: Record<string, Answer>) => request<void>("PUT", `/api/attempts/${id}/answers`, { answers }),
  submitAttempt: (id: number, answers: Record<string, Answer>) =>
    request<AttemptDetail>("POST", `/api/attempts/${id}/submit`, { answers }),
  deleteAttempt: (id: number) => request<void>("DELETE", `/api/attempts/${id}`),
};
