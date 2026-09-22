import Link from "next/link";
import type { components } from "@/lib/api/generated/public-api";
import { DataFreshness, EmptyState, RiskBadge, SourceList } from "@/components/ui/data-states";

type Schema = components["schemas"];

function duration(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return `${hours ? `${hours}h ` : ""}${minutes}m`;
}

export function RouteOptions({
  recommendation,
}: {
  recommendation: Schema["RecommendationResponse"] | null;
}) {
  if (!recommendation)
    return (
      <div className="route-options-empty">
        <span aria-hidden="true">⌁</span>
        <EmptyState message="Route options will appear after the live assessment completes." />
      </div>
    );
  const routes = [recommendation.primary_route, ...(recommendation.alternatives ?? [])].filter(
    (route): route is Schema["RouteCandidate"] => Boolean(route),
  );
  if (!routes.length)
    return (
      <div className="route-options-empty">
        <span aria-hidden="true">⌁</span>
        <EmptyState message="No route options are available for the selected mode and provider coverage." />
      </div>
    );
  return (
    <div className="route-options-list">
      {routes.map((route, index) => (
        <article className="route-option" data-primary={index === 0} key={route.route_id}>
          <div className="route-option-heading">
            <div>
              <span className="route-option-icon" aria-hidden="true">
                {index === 0 ? "✲" : "↗"}
              </span>
              <strong>{route.label.replaceAll("_", " ").toLowerCase()}</strong>
            </div>
            <RiskBadge risk={route.risk_level} />
          </div>
          <dl>
            <div>
              <dt>Travel time</dt>
              <dd>{duration(route.duration_seconds)}</dd>
            </div>
            <div>
              <dt>Distance</dt>
              <dd>
                {(route.distance_m / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}{" "}
                km
              </dd>
            </div>
            <div>
              <dt>Transfers</dt>
              <dd>{route.transfers ?? "Not available"}</dd>
            </div>
          </dl>
          {route.quality.flags.length > 0 && (
            <p className="route-quality">Quality: {route.quality.flags.join(", ")}</p>
          )}
          <details>
            <summary>Sources and freshness</summary>
            <SourceList sources={route.sources} />
            <DataFreshness freshness={recommendation.freshness} />
          </details>
          <Link
            className="route-option-link"
            href={`/trips/${recommendation.trip_id}/compare?candidate=${encodeURIComponent(route.route_id)}`}
          >
            Review this option <span aria-hidden="true">→</span>
          </Link>
        </article>
      ))}
    </div>
  );
}
