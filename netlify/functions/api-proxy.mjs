export default async function handler(request, context) {
  const backend = (process.env.BACKEND_API_URL || "").replace(/\/$/, "");
  if (!backend) {
    return new Response(JSON.stringify({ detail: "BACKEND_API_URL is not configured" }), {
      status: 500,
      headers: { "content-type": "application/json" },
    });
  }

  const url = new URL(request.url);
  const path = url.searchParams.get("path") || "/api/health";
  const targetUrl = backend + path;

  const headers = new Headers(request.headers);
  headers.set("x-access-password", process.env.ACCESS_PASSWORD || "");
  headers.delete("host");
  headers.delete("content-length");

  const init = {
    method: request.method,
    headers,
  };

  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = await request.arrayBuffer();
  }

  const response = await fetch(targetUrl, init);
  const responseHeaders = new Headers(response.headers);
  responseHeaders.set("access-control-allow-origin", "*");
  responseHeaders.set("access-control-allow-headers", "content-type, x-access-password, authorization");
  responseHeaders.set("access-control-allow-methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS");

  return new Response(response.body, {
    status: response.status,
    headers: responseHeaders,
  });
}
