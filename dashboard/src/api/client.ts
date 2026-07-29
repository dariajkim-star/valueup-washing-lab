// REST 접근 단일 지점(AD-11). /api 프리픽스는 Vite dev proxy가 FastAPI로 넘긴다.

export interface ApiError {
  detail: unknown;
  code?: string;
  status: number;
}

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly detail: unknown;
  constructor(e: ApiError) {
    super(typeof e.detail === "string" ? e.detail : `HTTP ${e.status}`);
    this.status = e.status;
    this.code = e.code;
    this.detail = e.detail;
  }
}

async function parseError(res: Response): Promise<ApiRequestError> {
  let body: { detail?: unknown; code?: string } = {};
  try {
    body = await res.json();
  } catch {
    /* 본문 없는 에러 */
  }
  return new ApiRequestError({
    detail: body.detail ?? res.statusText,
    code: body.code,
    status: res.status,
  });
}

// 쓰기 경로(현재는 /valueup/refresh 하나). GET과 달리 쿼리스트링이 아니라 경로에 대상을
// 담고, 응답 본문이 **무엇이 실제로 바뀌었는지**를 단계별로 돌려준다.
export async function apiPost<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const qs = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === "") continue;
      qs.append(k, String(v));
    }
  }
  const res = await fetch(`/api${path}${qs.toString() ? `?${qs}` : ""}`, { method: "POST" });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const qs = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      // 미선택(undefined/null/"")은 아예 보내지 않는다 — 2.6이 빈 문자열 필터를 422로
      // 거부하므로, 프론트는 미선택을 빈 파라미터로 흘려보내지 않는다.
      if (v === undefined || v === null || v === "") continue;
      qs.append(k, String(v));
    }
  }
  const url = `/api${path}${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    let body: { detail?: unknown; code?: string } = {};
    try {
      body = await res.json();
    } catch {
      /* 본문 없는 에러 */
    }
    throw new ApiRequestError({ detail: body.detail ?? res.statusText, code: body.code, status: res.status });
  }
  return (await res.json()) as T;
}
