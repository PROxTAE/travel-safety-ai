import { TripPlanner } from "@/features/trips/trip-planner";

export default async function TripPage({ params }: { params: Promise<{ tripId: string }> }) {
  const { tripId } = await params;
  return <TripPlanner tripId={tripId} />;
}
