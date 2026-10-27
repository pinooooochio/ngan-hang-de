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

/** Khung đề: ma trận phân bổ dùng lại khi ghép đề (không gồm câu chọn tay). */
export interface ExamTemplate {
  id: number;
  name: string;
  description: string;
  updated_at: string;
  n_questions: number;
  duration?: number;
  variants?: number;
  sections: SectionSpec[];
}

export type TemplateIn = Omit<ExamTemplate, "id" | "updated_at" | "n_questions">;

export interface TagMove {
  from: string;
  to: string;
  count: number;
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
  published: boolean;
  /** Chỉ có khi học viên xem: file được tải và yêu cầu tải đáp án. */
  files?: ExamFile[];
  request?: { status: RequestStatus; note: string | null } | null;
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
  user_id: number | null;
  user_name?: string | null;
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

export interface CurriculumTopic {
  ten: string;
  slug: string;
  names: string[];
  path: string;
  chuong: string;
  label?: string; // dòng gom câu mới gắn tới tầng chương hoặc học phần
  dang: string[];
  ghi_chu: string;
}

export interface CurriculumGrade {
  ten: string;
  slug: string;
  bac: string;
  ghi_chu: string;
  chuong: { ten: string; path: string }[];
  chu_de: CurriculumTopic[];
}

export interface Curriculum {
  grades: CurriculumGrade[];
  api: boolean;
  model: string;
  max_count: number;
}

export interface CoverageTopic {
  name: string;
  path: string;
  chuong: string;
  label?: string; // dòng gom câu mới gắn tới tầng chương hoặc học phần
  dang: string[];
  in_curriculum: boolean;
  counts: Record<string, { approved: number; draft: number }>;
}

export interface GenParams {
  grade: string;
  topic: string;
  dang?: string;
  level: Level;
  type: QType;
  count: number;
  notes?: string;
}

export interface GenItem {
  index: number;
  state: "new" | "duplicate" | "error";
  line: number;
  type: QType;
  stem: string;
  tags: string[][];
  errors: string[];
  warnings: string[];
  duplicate_of: string | null;
  code: string | null;
}

export interface GenBatch {
  id: number;
  mode: "api" | "manual";
  status: BuildState;
  params: GenParams;
  model: string | null;
  source: string;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  usage: { input_tokens: number; output_tokens: number; cache_read_input_tokens?: number } | null;
  n_added: number;
  n_duplicate: number;
  n_error: number;
}

export interface GenBatchDetail extends GenBatch {
  system_prompt: string;
  user_prompt: string;
  output: string | null;
  items: GenItem[];
}

export interface StoredBackup {
  name: string;
  size: number;
  modified: string;
  safety: boolean;
}

export interface BackupInfo {
  tables: { name: string; label: string; count: number }[];
  files: number;
  files_size: number;
  folder: string;
  backups: StoredBackup[];
}

export interface BackupSummary {
  created_at: string | null;
  app_version: string | null;
  database: string | null;
  tables: Record<string, number>;
  files: number;
  warnings: string[];
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

// ---------- Tài khoản và phân quyền ----------

export type Role = "admin" | "editor" | "student";
export type RequestStatus = "pending" | "approved" | "rejected";

export const ROLES: { value: Role; label: string }[] = [
  { value: "admin", label: "Admin" },
  { value: "editor", label: "Soạn đề" },
  { value: "student", label: "Học viên" },
];
export const roleLabel = (r: Role) => ROLES.find((x) => x.value === r)?.label ?? r;

export interface UserRow {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  role_name: string;
  active: boolean;
  created_at: string | null;
  last_login: string | null;
}

export interface AppSettings {
  student_quick: boolean;
}

export interface Me extends UserRow {
  settings: AppSettings;
  pending_requests?: number;
}

export interface LogEntry {
  id: number;
  code: string;
  username: string | null;
  action: string;
  action_name: string;
  detail: string | null;
  has_before: boolean;
  at: string;
}

export interface AnswerRequestRow {
  id: number;
  status: RequestStatus;
  note: string | null;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
  user: { id: number; username: string; display_name: string } | null;
  exam: { id: number; title: string } | null;
}

/** Lỗi từ máy chủ, giữ mã HTTP để phân biệt chưa đăng nhập (401) hay không có quyền (403). */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public data: unknown = null,
  ) {
    super(message);
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  // File (ví dụ bản sao lưu .zip) gửi nguyên nội dung, còn lại gửi JSON
  const raw = body instanceof Blob;
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": raw ? "application/zip" : "application/json" } : undefined,
    body: body !== undefined ? (raw ? body : JSON.stringify(body)) : undefined,
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    let data: unknown = null;
    try {
      data = await res.json();
      const detail = (data as { detail?: unknown }).detail;
      if (detail) msg = typeof detail === "string" ? detail : JSON.stringify(detail);
    } catch {
      /* giữ thông báo mặc định */
    }
    // phiên hết hạn hoặc bị đăng xuất: báo cho ứng dụng hiện trang đăng nhập
    if (res.status === 401 && !url.startsWith("/api/auth/")) window.dispatchEvent(new Event("nhd:unauthorized"));
    throw new ApiError(msg, res.status, data);
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
  bulkDelete: (codes: string[]) => request<{ deleted: number; kept: string[] }>("POST", "/api/questions/bulk-delete", { codes }),
  moveTag: (source: string, target: string) => request<{ moved: number }>("POST", "/api/tags/move", { source, target }),
  tagMoves: () => request<TagMove[]>("GET", "/api/tags/moves"),
  applyTagMoves: () => request<{ moved: number }>("POST", "/api/tags/moves/apply"),
  listTemplates: () => request<ExamTemplate[]>("GET", "/api/exam-templates"),
  createTemplate: (t: TemplateIn) => request<ExamTemplate>("POST", "/api/exam-templates", t),
  updateTemplate: (id: number, t: TemplateIn) => request<ExamTemplate>("PUT", `/api/exam-templates/${id}`, t),
  deleteTemplate: (id: number) => request<void>("DELETE", `/api/exam-templates/${id}`),
  bulk: (body: { codes: string[]; add_tag?: string; set_tag?: string; level?: Level; status?: Status }) =>
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
  me: () => request<Me>("GET", "/api/auth/me"),
  setup: (body: { username: string; password: string; display_name?: string }) =>
    request<UserRow>("POST", "/api/auth/setup", body),
  login: (username: string, password: string) => request<UserRow>("POST", "/api/auth/login", { username, password }),
  logout: () => request<void>("POST", "/api/auth/logout"),
  changePassword: (old_password: string, new_password: string) =>
    request<void>("POST", "/api/auth/password", { old_password, new_password }),
  updateMe: (display_name: string) => request<UserRow>("PUT", "/api/auth/me", { display_name }),
  listUsers: () => request<UserRow[]>("GET", "/api/users"),
  createUser: (body: { username: string; password: string; role: Role; display_name?: string }) =>
    request<UserRow>("POST", "/api/users", body),
  updateUser: (id: number, body: { display_name?: string; role?: Role; active?: boolean; password?: string }) =>
    request<UserRow>("PUT", `/api/users/${id}`, body),
  getSettings: () => request<AppSettings>("GET", "/api/settings"),
  saveSettings: (body: Partial<AppSettings>) => request<AppSettings>("PUT", "/api/settings", body),
  questionLog: (code: string) => request<LogEntry[]>("GET", `/api/questions/${encodeURIComponent(code)}/log`),
  logEntry: (id: number) => request<LogEntry & { before: string | null }>("GET", `/api/question-logs/${id}`),
  allLogs: (offset = 0, username?: string) =>
    request<{ total: number; items: LogEntry[] }>(
      "GET",
      `/api/question-logs?offset=${offset}${username ? `&username=${encodeURIComponent(username)}` : ""}`,
    ),
  publishExam: (id: number, published: boolean) => request<ExamSummary>("PUT", `/api/exams/${id}/published`, { published }),
  requestAnswers: (id: number) => request<ExamSummary>("POST", `/api/exams/${id}/answer-request`),
  listRequests: (status?: RequestStatus) =>
    request<AnswerRequestRow[]>("GET", `/api/answer-requests${status ? `?status=${status}` : ""}`),
  decideRequest: (id: number, status: "approved" | "rejected", note?: string) =>
    request<{ id: number; status: RequestStatus }>("PUT", `/api/answer-requests/${id}`, { status, note }),
  listExams: () => request<ExamSummary[]>("GET", "/api/exams"),
  createExam: (spec: ExamSpec) => request<ExamDetail>("POST", "/api/exams", spec),
  getExam: (id: number) => request<ExamDetail>("GET", `/api/exams/${id}`),
  rebuildExam: (id: number) => request<ExamDetail>("POST", `/api/exams/${id}/rebuild`),
  deleteExam: (id: number) => request<void>("DELETE", `/api/exams/${id}`),
  startAttempt: (body: { exam_id?: number; variant?: string; timed?: boolean; quick?: QuickSpec; retry_of?: number }) =>
    request<AttemptDetail>("POST", "/api/attempts", body),
  listAttempts: (examId?: number, all = false) => {
    const qs = new URLSearchParams();
    if (examId) qs.set("exam_id", String(examId));
    if (all) qs.set("all", "true");
    return request<AttemptSummary[]>("GET", `/api/attempts?${qs}`);
  },
  attemptStats: () => request<PracticeStats>("GET", "/api/attempts/stats"),
  getAttempt: (id: number) => request<AttemptDetail>("GET", `/api/attempts/${id}`),
  saveAnswers: (id: number, answers: Record<string, Answer>) => request<void>("PUT", `/api/attempts/${id}/answers`, { answers }),
  submitAttempt: (id: number, answers: Record<string, Answer>) =>
    request<AttemptDetail>("POST", `/api/attempts/${id}/submit`, { answers }),
  genCurriculum: () => request<Curriculum>("GET", "/api/gen/curriculum"),
  genCoverage: (grade: string) =>
    request<{ grade: string; slug: string; topics: CoverageTopic[] }>("GET", `/api/gen/coverage?grade=${encodeURIComponent(grade)}`),
  genPrompt: (p: GenParams) => request<{ system: string; user: string; combined: string }>("POST", "/api/gen/prompt", p),
  genCheck: (params: GenParams, output: string) => request<GenItem[]>("POST", "/api/gen/check", { params, output }),
  genCreate: (params: GenParams, mode: "api" | "manual", output?: string) =>
    request<GenBatchDetail>("POST", "/api/gen/batches", { params, mode, output }),
  genBatches: () => request<GenBatch[]>("GET", "/api/gen/batches"),
  genBatch: (id: number) => request<GenBatchDetail>("GET", `/api/gen/batches/${id}`),
  genRetry: (id: number) => request<GenBatchDetail>("POST", `/api/gen/batches/${id}/retry`),
  backupInfo: () => request<BackupInfo>("GET", "/api/backup/info"),
  backupSave: (files: boolean) => request<{ name: string }>("POST", `/api/backup/save?files=${files}`),
  backupDelete: (name: string) => request<void>("DELETE", `/api/backup/stored/${encodeURIComponent(name)}`),
  // Truyền file .zip tải lên, hoặc tên một bản trong thư mục sao lưu trên máy chủ
  backupInspect: (src: File | string) =>
    typeof src === "string"
      ? request<BackupSummary>("POST", `/api/backup/inspect?name=${encodeURIComponent(src)}`)
      : request<BackupSummary>("POST", "/api/backup/inspect", src),
  backupRestore: (src: File | string) =>
    typeof src === "string"
      ? request<BackupSummary & { safety_backup: string | null; relogin: boolean }>(
          "POST",
          `/api/backup/restore?name=${encodeURIComponent(src)}`,
        )
      : request<BackupSummary & { safety_backup: string | null; relogin: boolean }>("POST", "/api/backup/restore", src),
  deleteAttempt: (id: number) => request<void>("DELETE", `/api/attempts/${id}`),
};
