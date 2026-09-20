"use client";

import { Button } from "@heroui/react";
import { useRouter } from "next/navigation";

export function RoutePlaceholder({
  title,
  description,
}: Readonly<{ title: string; description: string }>) {
  const router = useRouter();

  return (
    <section className="page-card" aria-labelledby="page-title">
      <p className="muted">Smart Travel Assistant</p>
      <h1 id="page-title">{title}</h1>
      <p>{description}</p>
      <Button variant="secondary" onPress={() => router.push("/emergency")}>
        Open Emergency Center
      </Button>
    </section>
  );
}
