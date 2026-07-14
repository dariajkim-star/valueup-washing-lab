import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { RangeFilter } from "./FilterPanel";

afterEach(cleanup);

// 3차 재리뷰 반영 — 슬라이더 커밋 경로: pointerup/keyup/blur/pointercancel,
// 미설정 상태의 완전 no-op(호출 자체 금지, undefined 커밋 허용 아님), 중복 커밋 방지,
// 외부 값 동기화.

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
    expect(onCommit).toHaveBeenCalledTimes(1);
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

  it("pointercancel 시 변경값을 커밋한다(터치 스크롤 개입 경로)", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "12" } });
    fireEvent.pointerCancel(input);
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith(12);
  });

  it("미설정 상태에서 blur/pointerup 통과만으로는 커밋이 아예 발생하지 않는다(완전 no-op)", () => {
    // GPT 재리뷰 지적 반영: 이전 버전은 onCommit(undefined)를 호출해 부모의 patch()가
    // page를 리셋시켰다 — "호출 자체가 없어야" 진짜 no-op이다.
    const { input, onCommit } = setup(undefined);
    fireEvent.blur(input);
    fireEvent.pointerUp(input);
    fireEvent.pointerCancel(input);
    fireEvent.keyUp(input, { key: "Tab" });
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("pointerup 후 blur가 이어져도 한 번만 커밋한다(중복 방지)", () => {
    const { input, onCommit } = setup(10);
    fireEvent.change(input, { target: { value: "15" } });
    fireEvent.pointerUp(input);
    fireEvent.blur(input); // 같은 상호작용 뒤 이어지는 종료 이벤트
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith(15);
  });

  it("커밋 후 재상호작용하면 다시 커밋된다(dedup 플래그가 다음 조작을 막지 않음)", () => {
    const { input, onCommit } = setup();
    fireEvent.change(input, { target: { value: "8" } });
    fireEvent.pointerUp(input);
    fireEvent.change(input, { target: { value: "20" } });
    fireEvent.pointerUp(input);
    expect(onCommit).toHaveBeenCalledTimes(2);
    expect(onCommit).toHaveBeenNthCalledWith(2, 20);
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

  it("해제 버튼은 undefined 커밋(명시적 사용자 액션이므로 예외적으로 허용)", () => {
    const { onCommit } = setup(20);
    fireEvent.click(screen.getByText("해제"));
    expect(onCommit).toHaveBeenCalledWith(undefined);
  });
});
