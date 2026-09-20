import Image from "next/image";
import Link from "next/link";

export default function LoginPage() {
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
            <span aria-hidden="true" /> Sign-in unavailable
          </span>
          <h2 id="login-title">Welcome back</h2>
          <p>Sign-in is currently unavailable. You can still plan a trip or open emergency help.</p>
          <div className="login-disabled-action" aria-disabled="true">
            Sign in
          </div>
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
