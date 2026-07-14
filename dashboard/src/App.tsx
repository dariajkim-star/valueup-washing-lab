import { Route, Routes } from "react-router-dom";
import ScreenerList from "./pages/ScreenerList";
import CompanyDetail from "./pages/CompanyDetail";

// AC6: /company/:corpCode 딥링크. 리스트 필터 상태(zustand)는 전역 스토어라
// 라우트 전환에도 언마운트되지 않고 그대로 보존된다(뒤로가기 시 필터 유지).
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ScreenerList />} />
      <Route path="/company/:corpCode" element={<CompanyDetail />} />
    </Routes>
  );
}
