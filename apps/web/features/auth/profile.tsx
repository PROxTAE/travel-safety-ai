"use client";
import { useQuery } from "@tanstack/react-query";
import { signOut } from "next-auth/react";
import { useEffect } from "react";
import { api, ApiError } from "@/lib/api/client";
import { ErrorState } from "@/components/ui/data-states";

export function Profile() {
  const profile = useQuery({
    queryKey: ["me"],
    queryFn: async ({ signal }) => (await api.GET("/api/v1/me", { signal })).data!,
  });
  useEffect(() => {
    if (profile.error instanceof ApiError && profile.error.status === 401)
      void signOut({ callbackUrl: "/login" });
  }, [profile.error]);
  if (profile.isPending) return <span role="status">Loading profile…</span>;
  if (profile.error)
    return <ErrorState error={profile.error} retry={() => void profile.refetch()} />;
  return (
    <span className="profile-details">
      <strong>Hello, {profile.data.data.display_name || "Traveler"}!</strong>
      <button
        className="sign-out-button"
        type="button"
        onClick={() => void signOut({ callbackUrl: "/login" })}
      >
        <span aria-hidden="true">↪</span>
        <span className="sign-out-label">Sign out</span>
      </button>
    </span>
  );
}
