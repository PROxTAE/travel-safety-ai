import { RouteComparison } from "@/features/trips/route-comparison";

export default async function CompareRoutesPage({
  params,
  searchParams,
}: {
  params: Promise<{ tripId: string }>;
  searchParams?: Promise<{ candidate?: string }>;
}) {
  const { tripId } = await params;
  const search = await searchParams;
  return <RouteComparison tripId={tripId} candidateRouteId={search?.candidate} />;
}
