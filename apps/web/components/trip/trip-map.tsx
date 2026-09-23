"use client";

import { useEffect, useRef } from "react";
import maplibregl, {
  type GeoJSONSource,
  type LngLatBoundsLike,
  type StyleSpecification,
} from "maplibre-gl";
import type { components } from "@/lib/api/generated/public-api";

type Schema = components["schemas"];

export function getMapStyle(): StyleSpecification {
  const configured = process.env.NEXT_PUBLIC_MAP_TILE_URL;
  const token = process.env.NEXT_PUBLIC_MAP_TILE_TOKEN ?? "";
  const attribution =
    process.env.NEXT_PUBLIC_MAP_TILE_ATTRIBUTION ||
    "© OpenStreetMap contributors";

  if (configured) {
    const tile = configured.replace("{token}", encodeURIComponent(token));
    return {
      version: 8,
      sources: {
        base: { type: "raster", tiles: [tile], tileSize: 256, attribution },
      },
      layers: [{ id: "base", type: "raster", source: "base" }],
    };
  }

  // Development fallback. Deployments should set a tile URL whose usage policy
  // permits their expected traffic and provide its required attribution.
  return {
    version: 8,
    sources: {
      base: {
        type: "raster",
        tiles: [
          "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        ],
        tileSize: 256,
        attribution,
      },
    },
    layers: [{ id: "base", type: "raster", source: "base" }],
  };
}

export function TripMap({
  origin,
  destination,
  routes = [],
}: {
  origin: Schema["LocationRef"] | null;
  destination: Schema["LocationRef"] | null;
  routes?: Schema["RouteCandidate"][];
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);

  useEffect(() => {
    if (!container.current || map.current) return;
    map.current = new maplibregl.Map({
      container: container.current,
      style: getMapStyle(),
      center: [0, 20],
      zoom: 1.3,
      attributionControl: {},
    });
    map.current.addControl(new maplibregl.NavigationControl({ showCompass: true }), "top-left");
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    const update = () => {
      markers.current.forEach((marker) => marker.remove());
      markers.current = [];
      const points = [origin, destination].filter(Boolean) as Schema["LocationRef"][];
      points.forEach((location, index) => {
        const element = document.createElement("div");
        element.className = `trip-map-marker trip-map-marker-${index ? "destination" : "origin"}`;
        element.setAttribute(
          "aria-label",
          `${index ? "Destination" : "Origin"}: ${location.display_name}`,
        );
        markers.current.push(
          new maplibregl.Marker({ element })
            .setLngLat(location.coordinates.coordinates)
            .setPopup(new maplibregl.Popup({ offset: 20 }).setText(location.display_name))
            .addTo(instance),
        );
      });

      for (const [index, route] of routes.entries()) {
        const id = `trip-route-${index}`;
        const source = instance.getSource(id) as GeoJSONSource | undefined;
        const feature = { type: "Feature" as const, properties: {}, geometry: route.geometry };
        if (source) source.setData(feature);
        else {
          instance.addSource(id, { type: "geojson", data: feature });
          instance.addLayer({
            id,
            type: "line",
            source: id,
            paint: {
              "line-color": index === 0 ? "#08b88a" : "#60799d",
              "line-width": index === 0 ? 5 : 3,
              "line-dasharray": index === 0 ? [1, 0] : [2, 2],
            },
          });
        }
      }

      const coordinates = [
        ...points.map((location) => location.coordinates.coordinates),
        ...routes.flatMap((route) => route.geometry.coordinates),
      ];
      if (coordinates.length === 1) instance.easeTo({ center: coordinates[0], zoom: 8 });
      if (coordinates.length > 1) {
        const bounds = coordinates.reduce(
          (current, coordinate) => current.extend(coordinate),
          new maplibregl.LngLatBounds(coordinates[0], coordinates[0]),
        );
        instance.fitBounds(bounds as LngLatBoundsLike, { padding: 58, maxZoom: 10, duration: 500 });
      }
    };
    if (instance.loaded()) update();
    else instance.once("load", update);
  }, [origin, destination, routes]);

  return (
    <div className="trip-map-shell">
      <div ref={container} className="trip-map" aria-label="Interactive trip route map" />
    </div>
  );
}
