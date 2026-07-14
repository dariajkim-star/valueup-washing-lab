import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, ApiRequestError } from "./client";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: `HTTP ${status}`,
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("apiGet (3.3 리뷰 반영)", () => {
  it("undefined/null/빈 문자열 파라미터는 전송하지 않는다(2.6 빈 필터 422 계약)", async () => {
    const fn = mockFetch(200, { items: [] });
    await apiGet("/screening", {
      market: "", // 빈 문자열 → 제거
      sector: undefined, // → 제거
      washing_only: null, // → 제거
      min_roe: 10,
      page: 1,
    });
    const url = fn.mock.calls[0][0] as string;
    expect(url).toBe("/api/screening?min_roe=10&page=1");
    expect(url).not.toContain("market");
    expect(url).not.toContain("sector");
  });

  it("숫자 0과 false는 유효값으로 전송된다(빈 값과 구분)", async () => {
    const fn = mockFetch(200, {});
    await apiGet("/x", { min_roe: 0, washing_only: false });
    const url = fn.mock.calls[0][0] as string;
    expect(url).toContain("min_roe=0");
    expect(url).toContain("washing_only=false");
  });

  it("에러 계약 {detail, code} 파싱 → ApiRequestError", async () => {
    mockFetch(400, { detail: "invalid sort field: 'x'", code: "INVALID_SORT" });
    try {
      await apiGet("/screening", { sort: "x" });
      expect.unreachable("should throw");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiRequestError);
      const err = e as ApiRequestError;
      expect(err.status).toBe(400);
      expect(err.code).toBe("INVALID_SORT");
      expect(err.message).toContain("invalid sort field");
    }
  });

  it("FastAPI 422의 detail 배열(비문자열)도 크래시 없이 처리", async () => {
    mockFetch(422, {
      detail: [{ type: "date_from_datetime_parsing", loc: ["query", "as_of"] }],
      code: "VALIDATION_ERROR",
    });
    try {
      await apiGet("/screening", { as_of: "2026-02-30" });
      expect.unreachable("should throw");
    } catch (e) {
      const err = e as ApiRequestError;
      expect(err.status).toBe(422);
      expect(err.code).toBe("VALIDATION_ERROR");
      expect(Array.isArray(err.detail)).toBe(true);
      expect(err.message).toBe("HTTP 422"); // 비문자열 detail은 메시지로 캐스팅하지 않음
    }
  });

  it("본문 없는 에러(HTML 502 등)도 안전하게 throw", async () => {
    const fn = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.reject(new SyntaxError("not json")),
    });
    vi.stubGlobal("fetch", fn);
    await expect(apiGet("/x")).rejects.toBeInstanceOf(ApiRequestError);
  });
});
