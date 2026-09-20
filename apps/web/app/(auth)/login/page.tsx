import Link from "next/link";
import { RoutePlaceholder } from "@/components/ui/route-placeholder";

export default function LoginPage() {
  return (
    <main className="page-card">
      <p className="muted">Smart Travel Assistant</p>
      <h1>Welcome back</h1>
      <p>Authentication is connected to the real Keycloak OIDC provider in Phase 2.</p>
      <Link href="/emergency">Open Emergency Center</Link>
      <RoutePlaceholder
        title="Sign in is being prepared"
        description="No account or travel data is simulated in this shell."
      />
    </main>
  );
}
