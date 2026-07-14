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
