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
    <aside role="status" className="data-warning">
      ⚠{" "}
      {offline
        ? "You are offline. Current information is unavailable."
        : `Partial data: ${services.join(", ")} unavailable.`}
      {updatedAt && (
        <p>
          Last updated: <time dateTime={updatedAt}>{updatedAt}</time>
        </p>
      )}
    </aside>
  );
}
const risks = {
  LOW: ["●", "Low"],
  MEDIUM: ["▲", "Moderate"],
  HIGH: ["!", "High"],
  UNKNOWN: ["?", "Unknown"],
} as const;
const actions = {
  NORMAL: ["✓", "Travel as planned"],
  CHANGE_ROUTE: ["↪", "Change route"],
  DELAY: ["◷", "Delay travel"],
  AVOID: ["⛔", "Avoid travel"],
} as const;
export function RiskBadge({ risk }: { risk: Schema["RiskLevel"] }) {
  const [icon, label] = risks[risk] || risks.UNKNOWN;
  return (
    <span className="data-badge" data-risk={risk}>
      <span aria-hidden="true">{icon}</span> {label} risk
    </span>
  );
}
export function ActionBadge({ action }: { action: Schema["ActionCode"] }) {
  const item = actions[action];
  return (
    <span className="data-badge">
      <span aria-hidden="true">{item?.[0] || "?"}</span> {item?.[1] || "Action unavailable"}
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
