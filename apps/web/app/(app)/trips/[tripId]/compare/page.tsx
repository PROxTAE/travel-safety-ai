import { RoutePlaceholder } from "@/components/ui/route-placeholder";

export default function CompareRoutesPage() {
  return (
    <RoutePlaceholder
      title="Compare routes"
      description="Server-provided route alternatives will be compared here before you make a choice."
      iconSrc="/assets/icons/route.png"
      mascotSrc="/assets/mascot/mascot-warning.png"
    />
  );
}
