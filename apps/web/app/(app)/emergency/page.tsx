import { RoutePlaceholder } from "@/components/ui/route-placeholder";

export default function EmergencyPage() {
  return (
    <RoutePlaceholder
      title="Emergency Center"
      description="Emergency contacts, nearby services, and sharing controls will require your explicit consent."
      iconSrc="/assets/icons/sos-siren.png"
      mascotSrc="/assets/mascot/mascot-emergency-help.png"
    />
  );
}
