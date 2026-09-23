"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import maplibregl, { type Marker } from "maplibre-gl";
import type { components } from "@/lib/api/generated/public-api";
import { api } from "@/lib/api/client";
import { DataFreshness } from "@/components/ui/data-states";
import { getMapStyle } from "@/components/trip/trip-map";
import {
  IconCloudRain,
  IconTrain,
  IconDisaster,
  IconShield,
  IconAlertTriangle,
} from "@/components/ui/icons";

type Schema = components["schemas"];
type SafetyLayer = Schema["SafetyLayer"];
type SafetyEvent = Schema["SafetyEvent"];

interface LayerItem {
  id: SafetyLayer;
  label: string;
  enLabel: string;
  icon: ReactNode;
  iconSvgStr: string;
  color: string;
}

const LAYER_CONFIG: LayerItem[] = [
  {
    id: "WEATHER",
    label: "Weather Hazards",
    enLabel: "Weather Hazards",
    icon: <IconCloudRain width={18} height={18} />,
    iconSvgStr: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M16 14v6"/><path d="M8 14v6"/><path d="M12 16v6"/></svg>`,
    color: "#2F86F6",
  },
  {
    id: "TRANSPORT",
    label: "Transit Disruptions",
    enLabel: "Transit Disruptions",
    icon: <IconTrain width={18} height={18} />,
    iconSvgStr: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="3" width="16" height="16" rx="2"/><path d="M4 11h16"/><path d="M12 3v8"/><path d="m8 19-2 3"/><path d="m16 19 2 3"/></svg>`,
    color: "#FF9D1F",
  },
  {
    id: "DISASTER",
    label: "Natural Disasters",
    enLabel: "Natural Disasters",
    icon: <IconDisaster width={18} height={18} />,
    iconSvgStr: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m8 2 4 4-2 3 4 2-3 5 4 4"/><path d="M2 22h20"/><path d="m3 22 5-11 3 3 5-7 5 15"/></svg>`,
    color: "#F24E54",
  },
  {
    id: "OFFICIAL_ALERT",
    label: "Official Advisories",
    enLabel: "Official Advisories",
    icon: <IconShield width={18} height={18} />,
    iconSvgStr: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>`,
    color: "#08B88A",
  },
];


export function SafetyMapView() {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<Marker[]>([]);
  const [mapReady, setMapReady] = useState(false);

  const [selectedLayers, setSelectedLayers] = useState<SafetyLayer[]>([
    "WEATHER",
    "TRANSPORT",
    "DISASTER",
    "OFFICIAL_ALERT",
  ]);
  const [timeHorizon, setTimeHorizon] = useState<"now" | "6h" | "12h">("now");
  const [events, setEvents] = useState<SafetyEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<SafetyEvent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleLayer(layer: SafetyLayer) {
    if (selectedLayers.includes(layer)) {
      if (selectedLayers.length === 1) return; // keep at least one
      setSelectedLayers(selectedLayers.filter((l) => l !== layer));
    } else {
      setSelectedLayers([...selectedLayers, layer]);
    }
  }

  // Calculate timestamp based on timeHorizon only when timeHorizon changes
  const atTime = useMemo(() => {
    if (timeHorizon === "now") return undefined;
    const d = new Date();
    if (timeHorizon === "6h") d.setHours(d.getHours() + 6);
    if (timeHorizon === "12h") d.setHours(d.getHours() + 12);
    return d.toISOString();
  }, [timeHorizon]);

  // 1. Initialize MapLibre GL Map
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: getMapStyle(),
      center: [100.5018, 13.7563], // Thailand & Southeast Asia center
      zoom: 5,
      attributionControl: {},
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "top-left");
    map.addControl(new maplibregl.FullscreenControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("load", () => {
      setMapReady(true);
    });
    if (map.loaded()) {
      setMapReady(true);
    }

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      setMapReady(false);
    };
  }, []);

  // 2. Fetch events across all layers when time horizon changes
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const defaultBbox = "90.0,0.0,120.0,25.0";

    async function fetchSafetyEvents() {
      setLoading(true);
      setError(null);
      try {
        const res = await api.GET("/api/v1/safety/events", {
          params: {
            query: {
              bbox: defaultBbox,
              at: atTime,
              limit: 100,
            },
          },
          signal: controller.signal,
        });

        if (!cancelled && res.data?.data) {
          setEvents(res.data.data);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        console.error("fetchSafetyEvents error:", err);
        setError("ไม่สามารถโหลดข้อมูลเหตุการณ์ความปลอดภัยแบบเรียลไทม์ได้");
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void fetchSafetyEvents();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [atTime]);

  // Client-side instant filtering based on selected layers
  const visibleEvents = useMemo(() => {
    return events.filter((e) => selectedLayers.includes(e.layer));
  }, [events, selectedLayers]);

  // 3. Render real MapLibre Markers onto the Map
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // Clear existing markers
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    visibleEvents.forEach((event) => {
      const geom = event.geometry;
      let coords: [number, number] = [100.5018, 13.7563];

      if (geom.type === "Point" && Array.isArray(geom.coordinates)) {
        coords = geom.coordinates as [number, number];
      } else if (geom.type === "Polygon" && Array.isArray(geom.coordinates?.[0]?.[0])) {
        coords = geom.coordinates[0][0] as [number, number];
      }

      const isSelected = selectedEvent?.event_id === event.event_id;
      const markerEl = document.createElement("button");
      markerEl.type = "button";
      markerEl.className = `map-event-marker ${event.severity.toLowerCase()} ${isSelected ? "selected" : ""}`;
      markerEl.setAttribute("aria-label", `${event.title} - ${event.severity} severity`);

      const layerCfg = LAYER_CONFIG.find((l) => l.id === event.layer);
      const iconStr = layerCfg?.iconSvgStr || `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`;

      markerEl.innerHTML = `<span class="marker-icon">${iconStr}</span><span class="marker-pulse"></span>`;

      markerEl.addEventListener("click", () => {
        setSelectedEvent(event);
        map.easeTo({ center: coords, zoom: Math.max(map.getZoom(), 6), duration: 600 });
      });

      const popup = new maplibregl.Popup({ offset: 24, closeButton: false }).setHTML(`
        <div style="font-family: inherit; font-size: 13px; line-height: 1.4; padding: 2px;">
          <strong style="color: #0f172a; display: block; margin-bottom: 2px;">${event.title}</strong>
          <span style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #475569;">
            ${event.layer} • ${event.severity}
          </span>
        </div>
      `);

      const marker = new maplibregl.Marker({ element: markerEl, anchor: "center" })
        .setLngLat(coords)
        .setPopup(popup)
        .addTo(map);

      markersRef.current.push(marker);
    });

    return () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
    };
  }, [mapReady, visibleEvents, selectedEvent]);

  return (
    <div className="safety-map-page-layout">
      {/* 1. Control Sidebar / Floating Filter Bar */}
      <div className="safety-map-controls">
        <div className="map-control-header">
          <span className="map-badge">ข้อมูลสดทั่วโลก (Global Feeds)</span>
          <h1 className="map-title">Safety & Hazard Map</h1>
          <p className="map-subtitle">
            ข้อมูลเชิงพื้นที่หลายมิติแบบเรียลไทม์จากกรมอุตุนิยมวิทยา, Open-Meteo, USGS, GDACS และ NASA EONET
          </p>
        </div>


        {/* Time Horizon Selector */}
        <div className="control-section">
          <label className="section-label">ช่วงเวลาพยากรณ์ (Forecast Horizon)</label>
          <div className="time-horizon-pill-group" role="group" aria-label="ช่วงเวลา">
            <button
              type="button"
              className={`time-pill ${timeHorizon === "now" ? "active" : ""}`}
              onClick={() => setTimeHorizon("now")}
            >
              ขณะนี้ (Now)
            </button>
            <button
              type="button"
              className={`time-pill ${timeHorizon === "6h" ? "active" : ""}`}
              onClick={() => setTimeHorizon("6h")}
            >
              +6 ชั่วโมง
            </button>
            <button
              type="button"
              className={`time-pill ${timeHorizon === "12h" ? "active" : ""}`}
              onClick={() => setTimeHorizon("12h")}
            >
              +12 ชั่วโมง
            </button>
          </div>
        </div>

        {/* Risk Layer Toggles */}
        <div className="control-section">
          <label className="section-label">ชั้นข้อมูลความเสี่ยง (Risk Layers)</label>
          <div className="layer-toggle-list">
            {LAYER_CONFIG.map((layer) => {
              const active = selectedLayers.includes(layer.id);
              return (
                <button
                  key={layer.id}
                  type="button"
                  className={`layer-toggle-btn ${active ? "active" : ""}`}
                  onClick={() => toggleLayer(layer.id)}
                  aria-pressed={active}
                  aria-label={layer.enLabel}
                >
                  <span className="layer-icon" aria-hidden="true">
                    {layer.icon}
                  </span>
                  <span className="layer-label">{layer.label}</span>
                  <span
                    className="layer-indicator"
                    style={{ backgroundColor: active ? layer.color : "#d1d5db" }}
                  />
                </button>
              );
            })}
          </div>
        </div>

        {/* Legend / Status */}
        <div className="control-section map-legend-box">
          <label className="section-label">ระดับความรุนแรง (Severity Legend)</label>
          <div className="legend-items">
            <div className="legend-item">
              <span className="legend-dot dot-extreme" /> อันตรายขั้นวิกฤต (Extreme Hazard)
            </div>
            <div className="legend-item">
              <span className="legend-dot dot-high" /> ความเสี่ยงสูง (High Risk)
            </div>
            <div className="legend-item">
              <span className="legend-dot dot-mod" /> ความเสี่ยงปานกลาง (Moderate)
            </div>
            <div className="legend-item">
              <span className="legend-dot dot-info" /> แจ้งเตือนทั่วไป (Advisory / Info)
            </div>
          </div>
        </div>

        {/* Events Count summary */}
        <div className="events-count-banner">
          {error ? (
            <span className="text-red-500">{error}</span>
          ) : loading ? (
            <span>กำลังอัปเดตข้อมูลภัยพิบัติ…</span>
          ) : (
            <span>
              <strong>{visibleEvents.length}</strong> active hazard records in region
            </span>
          )}
        </div>
      </div>

      {/* 2. Real MapLibre Map Viewport */}
      <div className="safety-map-viewport">
        <div ref={mapContainerRef} className="maplibre-full-canvas" />

        {/* 3. Event Details Bottom / Side Drawer when marker clicked */}
        {selectedEvent && (
          <aside className="event-detail-drawer" aria-label="Event details">
            <div className="drawer-header">
              <div className="drawer-title-group">
                <span className={`severity-tag ${selectedEvent.severity.toLowerCase()}`}>
                  {selectedEvent.severity} SEVERITY
                </span>
                <span className="event-category-tag">{selectedEvent.event_type}</span>
              </div>
              <button
                type="button"
                className="close-drawer-btn"
                onClick={() => setSelectedEvent(null)}
                aria-label="ปิดรายละเอียดเหตุการณ์"
              >
                ✕
              </button>
            </div>

            <h2 className="event-detail-title">{selectedEvent.title}</h2>

            <div className="event-detail-meta">
              <div className="meta-box">
                <span className="meta-label">หน่วยงานผู้ออกประกาศ</span>
                <span className="meta-val">{selectedEvent.source?.authority || "UNKNOWN"}</span>
              </div>
              <div className="meta-box">
                <span className="meta-label">แหล่งข้อมูล (Provider)</span>
                <span className="meta-val">{selectedEvent.source?.provider || "UNKNOWN"}</span>
              </div>
              <div className="meta-box">
                <span className="meta-label">ประกาศอย่างเป็นทางการ</span>
                <span className="meta-val">{selectedEvent.official ? "ใช่ (Official)" : "ไม่"}</span>
              </div>
            </div>

            {selectedEvent.source && (
              <div className="event-provenance-section">
                <DataFreshness freshness={selectedEvent.source} />
              </div>
            )}

            <div className="drawer-actions">
              <Link
                href={`/trips/new?avoid_event=${encodeURIComponent(selectedEvent.event_id)}`}
                className="avoid-area-btn"
              >
                <IconAlertTriangle width={16} height={16} /> Avoid This Area in Trip Planner
              </Link>
            </div>

          </aside>
        )}
      </div>
    </div>
  );
}

