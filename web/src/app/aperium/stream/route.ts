/**
 * SSE pass-through for the collector's GET /api/stream (Postgres NOTIFY → Server-Sent Events).
 *
 * The `/aperium/*` rewrite in next.config.ts covers the REST calls, but the rewrite proxy
 * truncates long-lived event streams (seen under the Bun runtime: the stream stops
 * mid-event). This handler pipes the upstream body as a web-standard stream instead.
 * File routes take precedence over rewrites, so only this path is affected.
 */

const APERIUM_API_URL = process.env.APERIUM_API_URL ?? "http://127.0.0.1:8000";

export async function GET(request: Request) {
  let upstream: Response;
  try {
    upstream = await fetch(`${APERIUM_API_URL}/api/stream`, {
      headers: { accept: "text/event-stream" },
      cache: "no-store",
      signal: request.signal, // closing the EventSource closes the upstream connection
    });
  } catch {
    return new Response("AIS collector unreachable", { status: 502 });
  }
  if (!upstream.ok || !upstream.body) {
    return new Response(`AIS collector stream: HTTP ${upstream.status}`, { status: 502 });
  }
  return new Response(upstream.body, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      "x-accel-buffering": "no",
    },
  });
}
