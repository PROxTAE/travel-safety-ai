"use client";

export default function GlobalError({ reset }: Readonly<{ error: Error; reset: () => void }>) {
  return (
    <html lang="en">
      <body>
        <main className="page-card">
          <h1>Something needs attention</h1>
          <p>We could not render this page. Your emergency options remain available.</p>
          <button type="button" onClick={reset}>
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
