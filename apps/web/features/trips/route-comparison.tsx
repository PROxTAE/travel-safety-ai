"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { components } from "@/lib/api/generated/public-api";
import { api, ApiError } from "@/lib/api/client";
import {
  ActionBadge,
  DataFreshness,
  DataSkeleton,
  ErrorState,
  RiskBadge,
  SourceList,
} from "@/components/ui/data-states";
import {
  IconCheck,
  IconBell,
  IconShield,
  IconClock,
  IconRoute,
} from "@/components/ui/icons";

const TripMap = dynamic(
  () => import("@/components/trip/trip-map").then((module) => module.TripMap),
  {
    ssr: false,
    loading: () => <div className="trip-map-loading">กำลังโหลดแผนที่เปรียบเทียบเส้นทาง…</div>,
  },
);

type Schema = components["schemas"];

function formatDuration(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return `${hours ? `${hours} ชม. ` : ""}${minutes} นาที`;
}

export function RouteComparison({
  tripId,
  candidateRouteId,
}: {
  tripId: string;
  candidateRouteId?: string;
}) {
  const router = useRouter();
  const [trip, setTrip] = useState<Schema["Trip"] | null>(null);
  const [recommendation, setRecommendation] = useState<Schema["RecommendationResponse"] | null>(
    null,
  );
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(candidateRouteId || null);
  const [riskAcknowledged, setRiskAcknowledged] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [alertSubscribed, setAlertSubscribed] = useState(false);
  const [subscriptionId, setSubscriptionId] = useState<string | null>(null);
  const [feedbackSuccess, setFeedbackSuccess] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();

    async function loadData() {
      try {
        const tripRes = await api.GET("/api/v1/trips/{trip_id}", {
          params: { path: { trip_id: tripId } },
          signal: controller.signal,
        });

        if (!tripRes.data?.data) {
          throw new Error("ไม่พบข้อมูลทริปการเดินทาง");
        }

        const tripData = tripRes.data.data;
        setTrip(tripData);

        if (tripData.latest_request_id) {
          const runRes = await api.GET("/api/v1/runs/{request_id}", {
            params: { path: { request_id: tripData.latest_request_id } },
            signal: controller.signal,
          }).catch(() => null);

          if (runRes?.data?.data?.recommendation_id) {
            const recRes = await api.GET("/api/v1/recommendations/{recommendation_id}", {
              params: { path: { recommendation_id: runRes.data.data.recommendation_id } },
              signal: controller.signal,
            });

            if (recRes.data?.data) {
              const recData = recRes.data.data;
              setRecommendation(recData);

              // Default selected alternative
              if (!candidateRouteId) {
                const alt = recData.alternatives?.[0];
                if (alt) {
                  setSelectedRouteId(alt.route_id);
                }
              }
            }
          }
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        setLoading(false);
      }
    }

    void loadData();

    return () => {
      controller.abort();
    };
  }, [tripId, candidateRouteId]);

  if (loading) {
    return (
      <div className="comparison-container">
        <DataSkeleton label="กำลังโหลดข้อมูลเปรียบเทียบเส้นทาง…" />
      </div>
    );
  }

  if (error || !trip) {
    return (
      <div className="comparison-container">
        <ErrorState
          error={error || new Error("ไม่มีข้อมูลทริปการเดินทาง")}
          retry={() => window.location.reload()}
        />
      </div>
    );
  }

  const primaryRoute = recommendation?.primary_route;
  const alternatives = recommendation?.alternatives || [];
  const allRoutes = [primaryRoute, ...alternatives].filter(
    (r): r is Schema["RouteCandidate"] => Boolean(r),
  );
  const activeCandidate =
    alternatives.find((r) => r.route_id === selectedRouteId) || alternatives[0] || primaryRoute;

  const isPrimaryRisky =
    primaryRoute?.risk_level === "HIGH" || primaryRoute?.risk_level === "MEDIUM";

  async function handleApplyRoute(routeId: string) {
    if (!recommendation || !trip) return;
    setIsApplying(true);
    setError(null);

    try {
      await api.POST("/api/v1/trips/{trip_id}/apply-route", {
        params: {
          path: { trip_id: tripId },
          header: { "If-Match": String(trip.revision) },
        },
        body: {
          recommendation_id: recommendation.recommendation_id,
          route_id: routeId,
          risk_acknowledged: isPrimaryRisky && routeId === primaryRoute?.route_id ? riskAcknowledged : true,
        },
      });

      setFeedbackSuccess("นำเส้นทางที่เลือกไปใช้กับทริปของคุณเรียบร้อยแล้ว!");
      setTimeout(() => {
        router.push("/dashboard");
      }, 1500);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err
          : new Error("ไม่สามารถนำเส้นทางที่เลือกไปใช้ได้ กรุณาลองใหม่อีกครั้ง"),
      );
    } finally {
      setIsApplying(false);
    }
  }

  async function handleToggleAlerts() {
    try {
      if (alertSubscribed && subscriptionId) {
        await api.DELETE("/api/v1/alert-subscriptions/{subscription_id}", {
          params: { path: { subscription_id: subscriptionId } },
        });
        setAlertSubscribed(false);
        setSubscriptionId(null);
      } else {
        // Record consent then subscribe
        const consentRes = await api.POST("/api/v1/consents", {
          body: {
            type: "ALERT_NOTIFICATION",
            granted: true,
            policy_version: "1.0.0",
          },
        });

        const consentId = consentRes.data?.data?.consent_id || "00000000-0000-0000-0000-000000000000";

        const subRes = await api.POST("/api/v1/alert-subscriptions", {
          body: {
            trip_id: tripId,
            channel: "IN_APP",
            consent_id: consentId,
            min_severity: "MODERATE",
          },
        });

        if (subRes.data?.data) {
          setAlertSubscribed(true);
          setSubscriptionId(subRes.data.data.subscription_id);
        }
      }
    } catch {
      // Fallback toggle state
      setAlertSubscribed(!alertSubscribed);
    }
  }

  return (
    <div className="comparison-container">
      {/* Header breadcrumb */}
      <div className="comparison-header">
        <Link href="/dashboard" className="back-link">
          ← กลับหน้าแดชบอร์ด (Dashboard)
        </Link>
        <div className="comparison-title-row">
          <div>
            <span className="comparison-tag">Route Safety Comparison</span>
            <h1 className="comparison-title">
              {trip.origin.display_name} → {trip.destination.display_name}
            </h1>
          </div>
          {recommendation?.action_code && (
            <ActionBadge action={recommendation.action_code} />
          )}
        </div>
      </div>

      {feedbackSuccess && (
        <div className="toast-success-banner" role="status">
          <IconCheck width={16} height={16} /> {feedbackSuccess}
        </div>
      )}

      {/* Comparison Grid */}
      <div className="comparison-grid">
        {/* Left Card: Original / Primary Route */}
        <div
          className={`route-card-compare original-route-card ${isPrimaryRisky ? "risky-card" : ""}`}
        >
          <div className="card-top-badge">
            <span className="route-role-tag">Original Planned Route</span>
            {primaryRoute && <RiskBadge risk={primaryRoute.risk_level} />}
          </div>

          <h2 className="route-card-heading">
            {primaryRoute?.label || "เส้นทางตามกำหนดการเดิม"}
          </h2>

          <div className="route-stats-grid">
            <div className="stat-box">
              <span className="stat-label">ระยะเวลา (Duration)</span>
              <span className="stat-value">
                {primaryRoute ? formatDuration(primaryRoute.duration_seconds) : "—"}
              </span>
            </div>
            <div className="stat-box">
              <span className="stat-label">ระยะทาง (Distance)</span>
              <span className="stat-value">
                {primaryRoute
                  ? `${(primaryRoute.distance_m / 1000).toFixed(1)} กม.`
                  : "—"}
              </span>
            </div>
            <div className="stat-box">
              <span className="stat-label">การต่อรถ (Transfers)</span>
              <span className="stat-value">{primaryRoute?.transfers ?? 0} ครั้ง</span>
            </div>
          </div>

          <div className="route-hazard-exposure">
            <h4>การประเมินความปลอดภัย (Safety Assessment)</h4>
            <p>
              {recommendation?.reasons?.[0]?.text ||
                "เส้นทางมาตรฐานภายใต้การเฝ้าระวังปกติ"}
            </p>
          </div>

          {isPrimaryRisky && (
            <div className="risk-ack-box">
              <label className="risk-ack-label">
                <input
                  type="checkbox"
                  checked={riskAcknowledged}
                  onChange={(e) => setRiskAcknowledged(e.target.checked)}
                />
                <span>
                  I understand this route is flagged as <strong>{primaryRoute?.risk_level} RISK</strong> and accept full responsibility. (ฉันรับทราบและยอมรับความเสี่ยงของเส้นทางนี้)
                </span>
              </label>
            </div>
          )}

          <div className="route-card-action">
            <button
              type="button"
              className="keep-original-btn"
              disabled={isApplying || (isPrimaryRisky && !riskAcknowledged)}
              onClick={() => primaryRoute && handleApplyRoute(primaryRoute.route_id)}
            >
              ใช้เส้นทางเดิม (Keep Original Route)
            </button>
          </div>
        </div>

        {/* Right Card: Recommended Safer Route */}
        <div className="route-card-compare safer-route-card active-recommendation-card">
          <div className="card-top-badge">
            <span className="route-role-tag safer-tag">
              <IconShield width={14} height={14} /> Recommended Alternative
            </span>
            {activeCandidate && <RiskBadge risk={activeCandidate.risk_level} />}
          </div>


          <h2 className="route-card-heading">
            {activeCandidate?.label || "เส้นทางเลี่ยงจุดเสี่ยงภัย"}
          </h2>

          <div className="route-stats-grid">
            <div className="stat-box">
              <span className="stat-label">ระยะเวลา (Duration)</span>
              <span className="stat-value">
                {activeCandidate ? formatDuration(activeCandidate.duration_seconds) : "—"}
              </span>
            </div>
            <div className="stat-box">
              <span className="stat-label">ระยะทาง (Distance)</span>
              <span className="stat-value">
                {activeCandidate
                  ? `${(activeCandidate.distance_m / 1000).toFixed(1)} กม.`
                  : "—"}
              </span>
            </div>
            <div className="stat-box">
              <span className="stat-label">การต่อรถ (Transfers)</span>
              <span className="stat-value">{activeCandidate?.transfers ?? 0} ครั้ง</span>
            </div>
          </div>

          <div className="route-hazard-exposure safer-exposure">
            <h4>เหตุผลที่เส้นทางนี้ปลอดภัยกว่า (Why This is Safer)</h4>
            <p>
              {recommendation?.short_summary ||
                "เส้นทางทางเลือกนี้หลีกเลี่ยงศูนย์กลางพายุ พื้นที่น้ำท่วมขัง และเส้นทางคมนาคมที่อาจขัดข้อง"}
            </p>
          </div>

          {/* Alternative selector if multiple */}
          {alternatives.length > 1 && (
            <div className="alt-selector-row">
              <span>เลือกเส้นทางทางเลือก:</span>
              <select
                value={selectedRouteId || ""}
                onChange={(e) => setSelectedRouteId(e.target.value)}
                className="alt-select-dropdown"
              >
                {alternatives.map((alt) => (
                  <option key={alt.route_id} value={alt.route_id}>
                    {alt.label} ({formatDuration(alt.duration_seconds)}) - ระดับความเสี่ยง {alt.risk_level}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="route-card-action">
            <button
              type="button"
              className="apply-safer-btn"
              disabled={isApplying || !activeCandidate}
              onClick={() => activeCandidate && handleApplyRoute(activeCandidate.route_id)}
            >
              <IconCheck width={16} height={16} /> {isApplying ? "กำลังอัปเดตทริป…" : "ใช้เส้นทางที่ปลอดภัยกว่า (Apply Safer Route)"}
            </button>
          </div>
        </div>
      </div>

      {/* Side-by-Side Dual Map Comparison */}
      <div className="comparison-map-section">
        <div className="map-section-header">
          <h3>แผนที่เปรียบเทียบแนวระเบียงเส้นทาง (Interactive Corridor Comparison)</h3>
          <p>
            แสดงเส้นทางเดิมเปรียบเทียบกับเส้นทางเลี่ยงภัยพิบัติที่ได้รับการรับรองความปลอดภัย
          </p>
        </div>
        <div className="comparison-map-frame">
          <TripMap
            origin={trip.origin}
            destination={trip.destination}
            routes={allRoutes}
          />
        </div>
      </div>

      {/* Alert Subscription & Provenance Bar */}
      <div className="comparison-footer-bar">
        <div className="alert-toggle-box">
          <button
            type="button"
            className={`alert-sub-btn ${alertSubscribed ? "subscribed" : ""}`}
            onClick={handleToggleAlerts}
          >
            <IconBell width={16} height={16} />{" "}
            {alertSubscribed ? "เปิดรับการแจ้งเตือนความปลอดภัยแล้ว (ยกเลิกคลิก)" : "แจ้งเตือนฉันเมื่อเส้นทางมีการเปลี่ยนแปลง"}
          </button>
          <span className="alert-sub-desc">
            รับการแจ้งเตือนในระบบทันทีหากสภาพอากาศเลวร้ายหรือมีการปิดเส้นทางฉุกเฉินก่อนออกเดินทาง
          </span>
        </div>

        {recommendation?.freshness && (
          <div className="provenance-details-box">
            <DataFreshness freshness={recommendation.freshness} />
            {primaryRoute?.sources && <SourceList sources={primaryRoute.sources} />}
          </div>
        )}
      </div>
    </div>
  );
}

