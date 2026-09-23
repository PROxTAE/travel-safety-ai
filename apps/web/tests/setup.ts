import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

if (typeof window !== "undefined") {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  if (!window.URL.createObjectURL) {
    window.URL.createObjectURL = vi.fn(() => "blob:mock-url");
  }
  if (!window.URL.revokeObjectURL) {
    window.URL.revokeObjectURL = vi.fn();
  }
}

vi.mock("maplibre-gl", () => {
  class MockMap {
    container: HTMLElement;
    sources = new Map();
    layers = new Map();

    constructor(options: { container: HTMLElement | string }) {
      if (typeof options.container === "string") {
        this.container =
          document.getElementById(options.container) || document.createElement("div");
      } else {
        this.container = options.container;
      }
    }

    addControl = vi.fn();
    remove = vi.fn();
    getSource = vi.fn((id: string) => this.sources.get(id));
    addSource = vi.fn((id: string, source: unknown) => this.sources.set(id, source));
    addLayer = vi.fn((layer: { id: string }) => this.layers.set(layer.id, layer));
    easeTo = vi.fn();
    fitBounds = vi.fn();
    getZoom = vi.fn(() => 5);
    loaded = vi.fn(() => true);
    once = vi.fn((event: string, cb: () => void) => {
      if (event === "load") cb();
    });
    on = vi.fn();
  }

  class MockMarker {
    element: HTMLElement;
    constructor(options?: { element?: HTMLElement }) {
      this.element = options?.element || document.createElement("div");
    }
    setLngLat = vi.fn().mockReturnThis();
    setPopup = vi.fn().mockReturnThis();
    addTo = vi.fn((map: { container?: HTMLElement }) => {
      if (map && map.container && this.element) {
        map.container.appendChild(this.element);
      }
      return this;
    });
    remove = vi.fn(() => {
      this.element.remove();
      return this;
    });
  }

  class MockPopup {
    setText = vi.fn().mockReturnThis();
    setHTML = vi.fn().mockReturnThis();
  }

  class MockLngLatBounds {
    extend = vi.fn().mockReturnThis();
  }

  return {
    default: {
      Map: MockMap,
      Marker: MockMarker,
      Popup: MockPopup,
      NavigationControl: vi.fn(),
      FullscreenControl: vi.fn(),
      ScaleControl: vi.fn(),
      LngLatBounds: MockLngLatBounds,
    },
    Map: MockMap,
    Marker: MockMarker,
    Popup: MockPopup,
    NavigationControl: vi.fn(),
    FullscreenControl: vi.fn(),
    ScaleControl: vi.fn(),
    LngLatBounds: MockLngLatBounds,
  };
});

afterEach(cleanup);

