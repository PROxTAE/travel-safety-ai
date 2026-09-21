import Image from "next/image";
import Link from "next/link";
import { signIn } from "@/lib/auth";
import { safeReturnTo } from "@/lib/auth/session";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string; error?: string }>;
}) {
  const params = await searchParams;
  const available = Boolean(process.env.AUTH_SECRET && process.env.AUTH_KEYCLOAK_ISSUER);
  const returnTo = safeReturnTo(params.callbackUrl);
  return (
    <main className="login-shell">
      <section className="login-visual" aria-labelledby="login-visual-title">
        <Image
          className="login-route-art"
          src="/assets/login/decorations/login-route-overlay.png"
          width={860}
          height={300}
          alt=""
          priority
        />
        <div className="login-message">
          <h1 id="login-visual-title">
            Travel safer,
            <br />
            wherever you go.
          </h1>
          <p>Real-time guidance for every journey.</p>
        </div>
        <Image
          className="login-mascot"
          src="/assets/login/decorations/login-mascot-welcome.png"
          width={510}
          height={610}
          alt="Smart Travel Assistant elephant guide waving"
          priority
        />
      </section>

      <section className="login-panel" aria-labelledby="login-title">
        <div className="language-label" aria-label="Current language: English">
          <span aria-hidden="true">◎</span> English
        </div>
        <Image
          className="login-logo"
          src="/assets/login/brand/login-logo-horizontal.png"
          width={440}
          height={146}
          alt="Smart Travel Assistant"
          priority
        />
        <div className="login-card">
          <span className="availability-pill login-availability">
            <span aria-hidden="true" /> {available ? "Secure sign-in" : "Sign-in unavailable"}
          </span>
          <h2 id="login-title">Welcome back</h2>
          <p>
            {available
              ? "Sign in to access your profile and trips."
              : "Sign-in is currently unavailable. Emergency help remains accessible."}
          </p>
          {params.error && <p role="alert">Sign-in could not be completed. Please try again.</p>}
          <form
            action={async () => {
              "use server";
              await signIn("keycloak", { redirectTo: returnTo });
            }}
          >
            <button className="login-outline-action" type="submit" disabled={!available}>
              Sign in with Keycloak
            </button>
          </form>
          <div className="login-divider" aria-hidden="true">
            <span />
            <em>or</em>
            <span />
          </div>
          <Link className="login-outline-action" href="/trips/new">
            Continue to trip planning
          </Link>
        </div>
        <Link className="login-emergency-link" href="/emergency">
          <Image src="/assets/icons/sos-siren.png" width={30} height={30} alt="" />
          Need urgent help? <strong>Open Emergency Center</strong>
          <span aria-hidden="true">→</span>
        </Link>
      </section>
    </main>
  );
}
