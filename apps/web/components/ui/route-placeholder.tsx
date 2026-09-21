import Image from "next/image";
import Link from "next/link";

export function RoutePlaceholder({
  title,
  description,
  iconSrc = "/assets/branding/app-logo-mark.png",
  mascotSrc = "/assets/mascot/mascot-welcome.png",
}: Readonly<{
  title: string;
  description: string;
  iconSrc?: string;
  mascotSrc?: string;
}>) {
  return (
    <section className="route-screen" aria-labelledby="page-title">
      <header className="route-heading">
        <span className="route-heading-icon" aria-hidden="true">
          <Image src={iconSrc} width={58} height={58} alt="" />
        </span>
        <span>
          <h1 id="page-title">{title}</h1>
          <p>{description}</p>
        </span>
      </header>

      <div className="empty-workspace">
        <div className="empty-workspace-copy">
          <span className="availability-pill">
            <span aria-hidden="true" /> No live data available
          </span>
          <h2>Your travel information will appear here</h2>
          <p>
            When live sources are available, this page will show current information with its source
            and freshness.
          </p>
          <Link className="emergency-action" href="/emergency">
            Open Emergency Center
          </Link>
        </div>
        <div className="empty-workspace-art" aria-hidden="true">
          <Image src={mascotSrc} width={300} height={320} alt="" priority />
        </div>
      </div>
    </section>
  );
}
