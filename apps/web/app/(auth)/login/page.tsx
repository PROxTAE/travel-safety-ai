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
            เดินทางปลอดภัย
            <br />
            มั่นใจในทุกการเดินทาง
          </h1>
          <p>คำแนะนำและข้อมูลความปลอดภัยแบบเรียลไทม์สำหรับทุกเส้นทางของคุณ</p>
        </div>
        <Image
          className="login-mascot"
          src="/assets/login/decorations/login-mascot-welcome.png"
          width={510}
          height={610}
          alt="มาสคอตผู้ช่วยการเดินทาง"
          priority
        />
      </section>

      <section className="login-panel" aria-labelledby="login-title">
        <div className="language-label" aria-label="ภาษาปัจจุบัน: ภาษาไทย">
          <span aria-hidden="true">◎</span> ภาษาไทย (TH)
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
            <span aria-hidden="true" /> {available ? "เข้าสู่ระบบอย่างปลอดภัย" : "ระบบล็อกอินปิดชั่วคราว"}
          </span>
          <h2 id="login-title">ยินดีต้อนรับ (Welcome)</h2>
          <p>
            {available
              ? "เข้าสู่ระบบเพื่อจัดการโปรไฟล์และวางแผนทริปท่องเที่ยวของคุณ"
              : "ระบบล็อกอินปิดปรับปรุงชั่วคราว คุณยังสามารถเข้าใช้ศูนย์ช่วยเหลือฉุกเฉินได้"}
          </p>
          {params.error && <p role="alert">ไม่สามารถเข้าสู่ระบบได้ กรุณาลองใหม่อีกครั้ง</p>}
          <form
            action={async () => {
              "use server";
              await signIn("keycloak", { redirectTo: returnTo });
            }}
          >
            <button className="login-outline-action" type="submit" disabled={!available}>
              เข้าสู่ระบบด้วย Keycloak (Sign in)
            </button>
          </form>
          <div className="login-divider" aria-hidden="true">
            <span />
            <em>หรือ</em>
            <span />
          </div>
          <Link className="login-outline-action" href="/trips/new">
            วางแผนการเดินทางทันที (Trip Planner)
          </Link>
        </div>
        <Link className="login-emergency-link" href="/emergency">
          <Image src="/assets/icons/sos-siren.png" width={30} height={30} alt="" />
          ต้องการความช่วยเหลือเร่งด่วน? <strong>เปิดศูนย์ช่วยเหลือฉุกเฉิน</strong>
          <span aria-hidden="true">→</span>
        </Link>
      </section>
    </main>
  );
}

