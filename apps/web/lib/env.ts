import { z } from "zod";

const publicEnvironmentSchema = z.object({
  NEXT_PUBLIC_API_BASE_URL: z.url(),
  NEXT_PUBLIC_MAP_TILE_URL: z.string().url().optional().or(z.literal("")),
  NEXT_PUBLIC_MAP_TILE_TOKEN: z.string().optional(),
});

export type PublicEnvironment = z.infer<typeof publicEnvironmentSchema>;

type PublicEnvironmentInput = {
  NEXT_PUBLIC_API_BASE_URL?: string;
  NEXT_PUBLIC_MAP_TILE_URL?: string;
  NEXT_PUBLIC_MAP_TILE_TOKEN?: string;
};

export function getPublicEnvironment(
  environment: PublicEnvironmentInput = process.env as PublicEnvironmentInput,
): PublicEnvironment {
  return publicEnvironmentSchema.parse({
    NEXT_PUBLIC_API_BASE_URL: environment.NEXT_PUBLIC_API_BASE_URL,
    NEXT_PUBLIC_MAP_TILE_URL: environment.NEXT_PUBLIC_MAP_TILE_URL,
    NEXT_PUBLIC_MAP_TILE_TOKEN: environment.NEXT_PUBLIC_MAP_TILE_TOKEN,
  });
}
