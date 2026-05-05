export type OwnerQueryValue = string | number | boolean | null | undefined;

export function withOwnerQuery(
  path: string,
  ownerId: string | null,
  query?: Record<string, OwnerQueryValue>
): string {
  const [basePath, rawQuery = ""] = path.split("?", 2);
  const params = new URLSearchParams(rawQuery);

  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === null || value === undefined) continue;
      params.set(key, String(value));
    }
  }

  if (ownerId) params.set("owner_id", ownerId);

  const qs = params.toString();
  return qs ? `${basePath}?${qs}` : basePath;
}
