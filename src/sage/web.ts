/**
 * SAGE Web Search
 *
 * Small, server-side web search capability.
 * Search only for now; SAGE does not take actions on external sites.
 */

export interface WebSearchResult {
  title: string;
  url: string;
  snippet: string;
}

export async function searchWeb(
  query: string,
  limit = 5
): Promise<WebSearchResult[]> {
  const trimmed = query.trim();

  if (!trimmed) return [];

  const url =
    "https://html.duckduckgo.com/html/?q=" +
    encodeURIComponent(trimmed);

  const response = await fetch(url, {
    headers: {
      "User-Agent": "SAGE/1.0",
    },
  });

  if (!response.ok) {
    throw new Error(`Web search failed with status ${response.status}.`);
  }

  const html = await response.text();

  const results: WebSearchResult[] = [];

  const resultPattern =
    /<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>[\s\S]*?<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>/gi;

  for (const match of html.matchAll(resultPattern)) {
    if (results.length >= limit) break;

    const rawUrl = match[1];
    const rawTitle = match[2];
    const rawSnippet = match[3];

    const clean = (value: string): string =>
      value
        .replace(/<[^>]+>/g, " ")
        .replace(/&amp;/g, "&")
        .replace(/&quot;/g, '"')
        .replace(/&#x27;/g, "'")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/\s+/g, " ")
        .trim();

    const title = clean(rawTitle);
    const snippet = clean(rawSnippet);

    let resultUrl = rawUrl;

    try {
      const parsed = new URL(rawUrl);

      if (parsed.hostname.includes("duckduckgo.com")) {
        const redirected = parsed.searchParams.get("uddg");
        if (redirected) {
          resultUrl = redirected;
        }
      }
    } catch {
      continue;
    }

    if (title && resultUrl && snippet) {
      results.push({
        title,
        url: resultUrl,
        snippet,
      });
    }
  }

  return results;
}

/**
 * RAGforge: surface web results as numbered citations. Web results carry no
 * intrinsic confidence signal, so confidence is a documented rank heuristic
 * (1.0 minus a step per rank, floored at 0.5) and labeled as such.
 */
export function formatWebCitations(results: WebSearchResult[]): string {
  if (results.length === 0) return "";
  return results
    .map((result, index) => {
      const confidence = Math.max(0.5, 1.0 - 0.1 * index);
      return `[${index + 1}] ${result.title} (confidence ${confidence.toFixed(2)}, rank heuristic) — ${result.snippet} (${result.url})`;
    })
    .join("\n");
}
