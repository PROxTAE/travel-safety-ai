"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type Marker } from "maplibre-gl";
import { getMapStyle } from "@/components/trip/trip-map";
import type { components } from "@/lib/api/generated/public-api";

type Schema = components["schemas"];

interface DashboardMapProps {
  showRiskLayers: boolean;
  trip: Schema["Trip"] | null;
  routes: Schema["RouteCandidate"][];
  events: Schema["SafetyEvent"][];
  compareHref: string;
}

function safeCoords(loc: unknown): [number, number] | null {
  if (!loc) return null;
  if (Array.isArray(loc) && typeof loc[0] === "number" && typeof loc[1] === "number" && !isNaN(loc[0]) && !isNaN(loc[1])) {
    return [loc[0], loc[1]];
  }
  const obj = loc as Record<string, any>;
  if (Array.isArray(obj?.coordinates) && typeof obj.coordinates[0] === "number" && typeof obj.coordinates[1] === "number" && !isNaN(obj.coordinates[0]) && !isNaN(obj.coordinates[1])) {
    return [obj.coordinates[0], obj.coordinates[1]];
  }
  if (obj?.coordinates && typeof obj.coordinates === "object") {
    const nested = obj.coordinates;
    if (Array.isArray(nested?.coordinates) && typeof nested.coordinates[0] === "number" && typeof nested.coordinates[1] === "number" && !isNaN(nested.coordinates[0]) && !isNaN(nested.coordinates[1])) {
      return [nested.coordinates[0], nested.coordinates[1]];
    }
  }
  return null;
}

export function DashboardMap({
  showRiskLayers,
  trip,
  routes,
  events,
  compareHref,
}: DashboardMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<Marker[]>([]);
  const [mapLoaded, setMapLoaded] = useState(false);

  // 1. Initialize MapLibre GL instance once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const originPt = safeCoords(trip?.origin);
    const destPt = safeCoords(trip?.destination);
    const initialCenter: [number, number] =
      originPt && destPt
        ? [(originPt[0] + destPt[0]) / 2, (originPt[1] + destPt[1]) / 2]
        : originPt || destPt || [100.5018, 13.7563];

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: getMapStyle(),
      center: initialCenter,
      zoom: 6.2,
      attributionControl: {},
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");

    map.on("load", () => {
      setMapLoaded(true);
      map.resize();
    });

    if (map.loaded()) {
      setMapLoaded(true);
      map.resize();
    }

    mapRef.current = map;

    const resizeTimer = setTimeout(() => {
      map.resize();
    }, 200);

    return () => {
      clearTimeout(resizeTimer);
      map.remove();
      mapRef.current = null;
      setMapLoaded(false);
    };
  }, []); // Run once on mount

  // 2. Observe container resize for responsive redraws
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(() => {
      mapRef.current?.resize();
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // 3. Update route layers, markers, and bounds whenever data changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;

    // Clear old markers
    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = [];

    // 1. Primary / Recommended Route
    const recCoords: [number, number][] =
      routes.length > 0 && Array.isArray(routes[0]?.geometry?.coordinates)
        ? (routes[0].geometry.coordinates as [number, number][]).filter(
            (c) => Array.isArray(c) && c.length >= 2 && !isNaN(c[0]) && !isNaN(c[1])
          )
        : [];

    const recFeature = {
      type: "Feature" as const,
      properties: { name: "Recommended Route" },
      geometry: {
        type: "LineString" as const,
        coordinates: recCoords,
      },
    };

    const recSource = map.getSource("dashboard-rec-route") as GeoJSONSource | undefined;
    if (recSource) {
      recSource.setData(recFeature);
    } else {
      map.addSource("dashboard-rec-route", { type: "geojson", data: recFeature });
      if (!map.getLayer("dashboard-rec-route-line")) {
        map.addLayer({
          id: "dashboard-rec-route-line",
          type: "line",
          source: "dashboard-rec-route",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": "#059669", // Emerald Green
            "line-width": 5,
            "line-dasharray": [1.5, 1.5],
          },
        });
      }
    }

    // 2. Alternative Route
    const altCoords: [number, number][] =
      routes.length > 1 && Array.isArray(routes[1]?.geometry?.coordinates)
        ? (routes[1].geometry.coordinates as [number, number][]).filter(
            (c) => Array.isArray(c) && c.length >= 2 && !isNaN(c[0]) && !isNaN(c[1])
          )
        : [];

    const altFeature = {
      type: "Feature" as const,
      properties: { name: "Alternative Route" },
      geometry: {
        type: "LineString" as const,
        coordinates: altCoords,
      },
    };

    const altSource = map.getSource("dashboard-alt-route") as GeoJSONSource | undefined;
    if (altSource) {
      altSource.setData(altFeature);
    } else {
      map.addSource("dashboard-alt-route", { type: "geojson", data: altFeature });
      if (!map.getLayer("dashboard-alt-route-line")) {
        map.addLayer({
          id: "dashboard-alt-route-line",
          type: "line",
          source: "dashboard-alt-route",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": "#94a3b8", // Slate / Gray
            "line-width": 3,
            "line-dasharray": [3, 2],
          },
        });
      }
    }

    // 3. Origin & Destination Markers
    const originCoord = recCoords[0] || safeCoords(trip?.origin);
    const destCoord =
      (recCoords.length > 0 ? recCoords[recCoords.length - 1] : null) ||
      safeCoords(trip?.destination);

    const originName = trip?.origin?.display_name || "ต้นทาง (Origin)";
    const destName = trip?.destination?.display_name || "ปลายทาง (Destination)";

    if (originCoord) {
      const originEl = document.createElement("div");
      originEl.className = "dashboard-map-pin origin-pin";
      const originDot = document.createElement("span");
      originDot.className = "pin-dot";
      const originLabel = document.createElement("span");
      originLabel.className = "pin-label";
      originLabel.textContent = originName;
      originEl.append(originDot, originLabel);
      const originMarker = new maplibregl.Marker({ element: originEl, anchor: "center" })
        .setLngLat(originCoord)
        .addTo(map);
      markersRef.current.push(originMarker);
    }

    if (destCoord) {
      const destEl = document.createElement("div");
      destEl.className = "dashboard-map-pin dest-pin";
      const destIcon = document.createElement("span");
      destIcon.className = "pin-icon";
      destIcon.textContent = "●";
      const destLabel = document.createElement("span");
      destLabel.className = "pin-label";
      destLabel.textContent = destName;
      destEl.append(destIcon, destLabel);
      const destMarker = new maplibregl.Marker({ element: destEl, anchor: "bottom" })
        .setLngLat(destCoord)
        .addTo(map);
      markersRef.current.push(destMarker);
    }

    // 4. Fit map bounds
    const allCoords: [number, number][] = [...recCoords, ...altCoords];
    if (originCoord) allCoords.push(originCoord);
    if (destCoord) allCoords.push(destCoord);

    if (allCoords.length > 1) {
      const bounds = allCoords.reduce(
        (acc, coord) => acc.extend(coord),
        new maplibregl.LngLatBounds(allCoords[0], allCoords[0]),
      );
      map.fitBounds(bounds, { padding: 50, maxZoom: 9, duration: 400 });
    } else if (allCoords.length === 1) {
      map.flyTo({ center: allCoords[0], zoom: 7 });
    }
  }, [routes, showRiskLayers, trip, events, mapLoaded]);

  return (
    <div className="dashboard-map-container">
      <div
        ref={containerRef}
        className="dashboard-map-canvas"
        aria-label="แผนที่เส้นทางและความเสี่ยงแบบอินเทอร์แอคทีฟ"
      />

      {/* Floating Bottom Card: Safer route found + Legend */}
      <div className="dashboard-map-bottom-bar">
        {routes.length > 1 && (
          <Link href={compareHref} className="dashboard-map-safer-pill">
            <div className="safer-pill-badge" aria-hidden="true">
              ✓
            </div>
            <div className="safer-pill-copy">
              <strong className="safer-title">เปรียบเทียบเส้นทางที่ระบบประเมิน</strong>
              <span className="safer-sub">ดูระยะทาง เวลา และความเสี่ยงจากผลประเมิน</span>
            </div>
            <span className="safer-arrow" aria-hidden="true">
              ›
            </span>
          </Link>
        )}

        <div className="dashboard-map-legend" role="region" aria-label="คำอธิบายสัญลักษณ์เส้นทาง">
          <div className="legend-row">
            <span className="legend-sample rec-dots" aria-hidden="true">
              •••••
            </span>
            <span className="legend-label">เส้นทางแนะนำ</span>
          </div>
          <div className="legend-row">
            <span className="legend-sample alt-dashes" aria-hidden="true">
              -----
            </span>
            <span className="legend-label">เส้นทางสำรอง</span>
          </div>
        </div>
      </div>
    </div>
  );
}
