"use client";

import { useEffect, useId, useState } from "react";
import type { components } from "@/lib/api/generated/public-api";
import { api } from "@/lib/api/client";
import { ErrorState } from "@/components/ui/data-states";

type Location = components["schemas"]["LocationRef"];

export function LocationSearch({
  label,
  value,
  onChange,
}: {
  label: string;
  value: Location | null;
  onChange: (location: Location | null) => void;
}) {
  const id = useId();
  const [query, setQuery] = useState(value?.display_name ?? "");
  const [results, setResults] = useState<Location[]>([]);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [selectedName, setSelectedName] = useState(value?.display_name ?? "");

  useEffect(() => {
    if (query.trim().length < 2 || query === selectedName) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      setError(null);
      void api
        .GET("/api/v1/locations/search", {
          params: { query: { q: query.trim(), limit: 5 } },
          signal: controller.signal,
        })
        .then(({ data }) => {
          if (!controller.signal.aborted) {
            setResults(data?.data ?? []);
            setActive(-1);
          }
        })
        .catch((reason: Error) => {
          if (reason.name !== "AbortError") setError(reason);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 400);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, selectedName]);

  const choose = (location: Location) => {
    const unconfirmed = { ...location, confirmed_by_user: false };
    setSelectedName(location.display_name);
    setQuery(location.display_name);
    setResults([]);
    setActive(-1);
    onChange(unconfirmed);
  };

  return (
    <div className="location-search">
      <label htmlFor={id}>{label}</label>
      <div className="location-input-wrap">
        <span aria-hidden="true">📍</span>
        <input
          id={id}
          value={query}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={Boolean(results.length)}
          aria-controls={`${id}-results`}
          aria-activedescendant={active >= 0 ? `${id}-result-${active}` : undefined}
          autoComplete="off"
          placeholder={`Search ${label.toLowerCase()}`}
          onChange={(event) => {
            setSelectedName("");
            setQuery(event.target.value);
            setResults([]);
            setLoading(false);
            setError(null);
            onChange(null);
          }}
          onKeyDown={(event) => {
            if (!results.length) return;
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActive((current) => (current + 1) % results.length);
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((current) => (current <= 0 ? results.length - 1 : current - 1));
            } else if (event.key === "Enter" && active >= 0) {
              event.preventDefault();
              choose(results[active]);
            } else if (event.key === "Escape") setResults([]);
          }}
        />
        {query && (
          <button
            type="button"
            className="location-clear"
            aria-label={`Clear ${label}`}
            onClick={() => {
              setSelectedName("");
              setQuery("");
              setResults([]);
              setLoading(false);
              setError(null);
              onChange(null);
            }}
          >
            ×
          </button>
        )}
      </div>
      {loading && <span className="location-note">Searching real geocoding…</span>}
      {error && <ErrorState error={error} />}
      {!loading &&
        query.trim().length >= 2 &&
        !error &&
        !results.length &&
        query !== selectedName && <span className="location-note">No matching places found.</span>}
      {results.length > 0 && (
        <ul id={`${id}-results`} role="listbox" className="location-results">
          {results.map((location, index) => (
            <li
              id={`${id}-result-${index}`}
              role="option"
              aria-selected={index === active}
              key={`${location.provider}:${location.place_id ?? location.display_name}`}
            >
              <button type="button" onClick={() => choose(location)}>
                <strong>{location.display_name}</strong>
                <span>
                  {[location.admin1, location.country_code, location.timezone]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {value && (
        <div className="location-confirmation" data-confirmed={value.confirmed_by_user}>
          <span>
            {value.confirmed_by_user
              ? "✓ Pin confirmed"
              : "Check the pin on the map before continuing."}
          </span>
          {!value.confirmed_by_user && (
            <button type="button" onClick={() => onChange({ ...value, confirmed_by_user: true })}>
              Confirm this pin
            </button>
          )}
        </div>
      )}
    </div>
  );
}
