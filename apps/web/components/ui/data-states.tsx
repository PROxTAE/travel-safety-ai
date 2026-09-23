"use client";
import { useEffect, useState } from "react";
import type { components } from "@/lib/api/generated/public-api";
type Schema = components["schemas"];

export function DataFreshness({ freshness }: { freshness: Schema["Freshness"] }) {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    const timer = setInterval(tick, 30_000);
    return () => clearInterval(timer);
  }, []);
  const stale = freshness.expires_at && Date.parse(freshness.expires_at) <= now;
  return (
    <div className="data-freshness">
      <span>{stale ? "Stale data" : "Data timestamps"}</span>
      <br />
      Observed:{" "}
      {freshness.observed_at ? (
        <time dateTime={freshness.observed_at}>{freshness.observed_at}</time>
      ) : (
        "Not available"
      )}
      <br />
      Fetched: <time dateTime={freshness.fetched_at}>{freshness.fetched_at}</time>
      {freshness.expires_at && (
        <>
          <br />
          Expires: <time dateTime={freshness.expires_at}>{freshness.expires_at}</time>
        </>
      )}
    </div>
  );
}
export function SourceList({ sources }: { sources: Schema["SourceProvenance"][] }) {
  if (!sources.length) return <EmptyState message="Sources not available." />;
  return (
    <ul aria-label="Sources">
      {sources.map((source) => (
        <li key={source.source_id}>
          {source.source_url && /^https?:\/\//i.test(source.source_url) ? (
            <a href={source.source_url} target="_blank" rel="noopener noreferrer">
              {source.provider}
            </a>
          ) : (
            source.provider
          )}
          <span> · {source.authority}</span>
          {source.attribution && <p>{source.attribution}</p>}
          {source.license && <p>License: {source.license}</p>}
          <DataFreshness freshness={source} />
        </li>
      ))}
    </ul>
  );
}
import {
  IconAlertTriangle,
  IconCheck,
  IconClock,
  IconShield,
} from "@/components/ui/icons";

export function DegradedBanner({
  services = [],
  offline = false,
  updatedAt,
}: {
  services?: string[];
  offline?: boolean;
  updatedAt?: string;
}) {
  if (!offline && !services.length) return null;
  return (
    <aside role="status" className="data-warning" style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <IconAlertTriangle width={18} height={18} />
      <div>
        {offline
          ? "You are offline. Current information is unavailable. (คุณกำลังออฟไลน์)"
          : `Partial data: ${services.join(", ")} unavailable.`}
        {updatedAt && (
          <p>
            อัปเดตล่าสุด (Last updated): <time dateTime={updatedAt}>{updatedAt}</time>
          </p>
        )}
      </div>
    </aside>
  );
}
const risks = {
  LOW: ["Low", "#08B88A"],
  MEDIUM: ["Moderate", "#FF9D1F"],
  HIGH: ["High", "#F24E54"],
  UNKNOWN: ["Unknown", "#64748b"],
} as const;

const actions = {
  NORMAL: ["Travel as planned (เดินทางตามแผน)", <IconCheck key="n" width={14} height={14} />],
  CHANGE_ROUTE: ["Change route (เปลี่ยนเส้นทาง)", <IconShield key="cr" width={14} height={14} />],
  DELAY: ["Delay travel (ชะลอการเดินทาง)", <IconClock key="d" width={14} height={14} />],
  AVOID: ["Avoid travel (หลีกเลี่ยงการเดินทาง)", <IconAlertTriangle key="a" width={14} height={14} />],
} as const;

export function RiskBadge({ risk }: { risk: Schema["RiskLevel"] }) {
  const [label, color] = risks[risk] || risks.UNKNOWN;
  return (
    <span className="data-badge" data-risk={risk}>
      <span
        aria-hidden="true"
        style={{
          display: "inline-block",
          width: 8,
          height: 8,
          borderRadius: "50%",
          backgroundColor: color,
          marginRight: 4,
        }}
      />
      {label} risk
    </span>
  );
}

export function ActionBadge({ action }: { action: Schema["ActionCode"] }) {
  const item = actions[action];
  return (
    <span className="data-badge" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      {item?.[1] || <span aria-hidden="true">?</span>}
      <span>{item?.[0] || "Action unavailable"}</span>
    </span>
  );
}

export function DataSkeleton({ label = "Loading data…" }: { label?: string }) {
  return (
    <div role="status" aria-busy="true" className="data-skeleton">
      {label}
    </div>
  );
}
export function EmptyState({ message = "No data available." }: { message?: string }) {
  return <p role="status">{message}</p>;
}
export function ErrorState({ error, retry }: { error: Error; retry?: () => void }) {
  return (
    <div role="alert">
      <p>
        {error.name === "ApiError"
          ? error.message
          : "Information is unavailable. Please try again."}
      </p>
      {retry && <button onClick={retry}>Try again</button>}
    </div>
  );
}
