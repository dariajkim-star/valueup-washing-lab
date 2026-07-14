import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MetricPoint } from "../../api/detail";

// UX-DR3 지표 분기 시계열(3.2 시안 재현) — ROE 분기별 바차트.
export function MetricsChart({ metrics }: { metrics: MetricPoint[] }) {
  const data = metrics
    .filter((m) => m.roe !== null)
    .map((m) => ({ label: `${String(m.year).slice(2)}Q${m.quarter}`, roe: m.roe }));

  if (data.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-400">ROE 시계열 데이터가 없습니다</p>;
  }

  return (
    <div className="h-[180px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
          <YAxis hide />
          <Tooltip
            formatter={(v) => [`${Number(v).toFixed(1)}%`, "ROE"]}
            contentStyle={{ fontSize: 12, borderRadius: 8 }}
          />
          <Bar dataKey="roe" radius={[4, 4, 0, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={i === data.length - 1 ? "#0e9f6e" : "#a7f3d0"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
