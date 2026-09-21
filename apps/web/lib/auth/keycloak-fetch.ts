// Only an operator-configured origin may be substituted, never an incoming URL.
// Preserve Host so Keycloak's discovery document uses its canonical public issuer.
export const keycloakFetch: typeof fetch = (input, init) => {
  const url = new URL(input instanceof Request ? input.url : input.toString());
  const publicIssuer = process.env.AUTH_KEYCLOAK_ISSUER;
  const internalOrigin = process.env.AUTH_KEYCLOAK_INTERNAL_ORIGIN;
  const headers = new Headers(init?.headers);
  if (publicIssuer && internalOrigin && url.origin === new URL(publicIssuer).origin) {
    headers.set("Host", url.host);
    const target = new URL(internalOrigin);
    url.host = target.host;
    url.protocol = target.protocol;
  }
  return fetch(url, {
    ...init,
    headers,
    signal: init?.signal ?? AbortSignal.timeout(10_000),
    redirect: "error",
  });
};
