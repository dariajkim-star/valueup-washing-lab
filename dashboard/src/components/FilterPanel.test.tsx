import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { RangeFilter } from "./FilterPanel";

afterEach(cleanup);

// 재리뷰 #3 — 슬라이더 커밋 경로(pointerup/keyup/blur/pointercancel)·외부 값 동기화·
// 미설정 상태 가드(blur 통과만으로 min값이 커밋되면 안 됨).

function setup(value?: number) {
  const onCommit = vi.fn();
  render(
    <RangeFilter label="ROE ≥" unit="%" min={0} max={30} step={1} value={value} onCommit={onCommit} />,
  );
  const input = screen.getByLabelText("ROE ≥") as HTMLInputElement;
  return { input, onCommit };
}

describe("RangeFilter", () => {
  it("change 후 pointerup에 커밋(값은 valueAsNumber)", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "15" } });
    expect(onCommit).not.toHaveBeenCalled(); // 드래그 중엔 커밋 안 함
    fireEvent.pointerUp(input);
    expect(onCommit).toHaveBeenCalledWith(15);
  });

  it("blur로도 커밋된다(포커스 이탈 경로)", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "10" } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith(10);
  });

  it("키보드 조작(keyup) 커밋", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "5" } });
    fireEvent.keyUp(input, { key: "ArrowRight" });
    expect(onCommit).toHaveBeenCalledWith(5);
  });

  it("미설정 상태에서 blur/pointerup 통과만으로는 필터가 활성화되지 않는다(min값 커밋 금지)", () => {
    const { input, onCommit } = setup(undefined);
    fireEvent.blur(input); // 탭으로 지나가기만 함
    fireEvent.pointerUp(input);
    // undefined 커밋(no-op)만 허용 — 숫자 커밋이 있으면 안 됨
    for (const call of onCommit.mock.calls) {
      expect(call[0]).toBeUndefined();
    }
  });

  it("외부 value 변경(전체 초기화 등)에 로컬 상태가 동기화된다", () => {
    const onCommit = vi.fn();
    const { rerender } = render(
      <RangeFilter label="PBR ≤" unit="x" min={0} max={5} step={0.1} value={3} onCommit={onCommit} />,
    );
    expect(screen.getByText("3x")).toBeTruthy();
    rerender(
      <RangeFilter label="PBR ≤" unit="x" min={0} max={5} step={0.1} value={undefined} onCommit={onCommit} />,
    );
    expect(screen.getByText("전체")).toBeTruthy(); // local이 undefined로 동기화됨
  });

  it("해제 버튼은 undefined 커밋", () => {
    const { onCommit } = setup(20);
    fireEvent.click(screen.getByText("해제"));
    expect(onCommit).toHaveBeenCalledWith(undefined);
  });
});
