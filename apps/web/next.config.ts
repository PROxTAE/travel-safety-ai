import createBundleAnalyzer from "@next/bundle-analyzer";
import type { NextConfig } from "next";

const withBundleAnalyzer = createBundleAnalyzer({
  enabled: process.env.ANALYZE === "true",
});

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // The isolated Docker browser reaches the dev server through its Compose DNS name.
  allowedDevOrigins: ["web"],
  // The fixed development badge overlaps one of the shell's responsive controls.
  devIndicators: false,
  images: {
    formats: ["image/avif", "image/webp"],
  },
};

export default withBundleAnalyzer(nextConfig);
