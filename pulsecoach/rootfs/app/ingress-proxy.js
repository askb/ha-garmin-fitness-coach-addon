/**
 * HA Ingress Proxy — rewrites Next.js HTML to work behind HA ingress.
 *
 * Problem: HA ingress serves the addon at /api/hassio_ingress/<token>/
 * but Next.js emits absolute paths like /_next/static/... which the
 * browser resolves against the HA host, bypassing ingress → 404.
 *
 * Solution: This proxy sits between HA ingress (port 3000) and Next.js
 * (port 3001). For HTML responses, it rewrites absolute paths to include
 * the ingress prefix from the X-Ingress-Path header. Non-HTML responses
 * (JS, CSS, images, API) pass through unchanged.
 */
const http = require("http");

const NEXT_PORT = parseInt(process.env.NEXT_INTERNAL_PORT || "3001", 10);
const LISTEN_PORT = parseInt(process.env.PORT || "3000", 10);

const server = http.createServer((clientReq, clientRes) => {
  const ingressPath = clientReq.headers["x-ingress-path"] || "";

  // Strip ingress prefix from incoming URL before forwarding to Next.js
  let forwardPath = clientReq.url;
  if (ingressPath && forwardPath.startsWith(ingressPath)) {
    forwardPath = forwardPath.substring(ingressPath.length) || "/";
  }

  // Strip accept-encoding so Next.js returns uncompressed HTML
  const headers = { ...clientReq.headers };
  if (ingressPath) {
    delete headers["accept-encoding"];
  }

  const proxyOpts = {
    hostname: "127.0.0.1",
    port: NEXT_PORT,
    path: forwardPath,
    method: clientReq.method,
    headers: headers,
  };

  const proxyReq = http.request(proxyOpts, (proxyRes) => {
    const ct = proxyRes.headers["content-type"] || "";
    const isHtml = ct.includes("text/html");

    // Rewrite /_next/ in ALL text-based responses, not just HTML.
    // Next.js emits /_next/ references in many response types:
    //   - HTML: <script src>, <link href>, RSC inline data
    //   - JS: turbopack runtime base path, dynamic import paths
    //   - CSS: @font-face url() references
    //   - RSC flight responses (text/x-component): module references
    //   - text/plain: fallback content-type for some Next.js responses
    // Rewriting only HTML leaves JS/CSS/RSC with raw /_next/ paths that
    // bypass ingress → 404 → React hydration fails.
    const isText =
      ct.includes("text/") ||
      ct.includes("javascript") ||
      ct.includes("json") ||
      ct.includes("x-component");
    const needsRewrite = ingressPath && isText;

    console.log(
      `[ingress-proxy] ${clientReq.method} ${clientReq.url} → fwd:${forwardPath} → ${proxyRes.statusCode} (${ct.split(";")[0]}${needsRewrite ? " REWRITE" : ""})`,
    );

    if (needsRewrite) {
      // Buffer response and rewrite /_next/ paths
      const chunks = [];
      proxyRes.on("data", (c) => chunks.push(c));
      proxyRes.on("end", () => {
        let body = Buffer.concat(chunks).toString("utf-8");

        // Core rewrite: prefix all /_next/ with ingress path.
        // Safe because /_next/ is a unique Next.js prefix that only appears
        // in URL references. The proxy always receives raw content from
        // Next.js (never already-rewritten content), so no double-prefix risk.
        body = body.replaceAll("/_next/", ingressPath + "/_next/");

        if (isHtml) {
          // HTML-specific: rewrite href/src/action attributes for non-_next
          // absolute paths. Uses regex to only match HTML attributes, NOT
          // inline script/JSON content (avoids corrupting RSC payloads).
          const escaped = ingressPath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          const attrRegex = new RegExp(
            `((?:src|href|action)=["'])(/)(?!/|${escaped.slice(1)}|_next/)`,
            "g",
          );
          body = body.replace(attrRegex, `$1${ingressPath}/`);

          // Inject ingress path into a meta tag so client JS can read it
          body = body.replace(
            "<head>",
            `<head><meta name="ingress-path" content="${ingressPath}">`,
          );
        }

        const resHeaders = { ...proxyRes.headers };
        delete resHeaders["content-length"];
        delete resHeaders["transfer-encoding"];
        resHeaders["content-length"] = Buffer.byteLength(body);

        clientRes.writeHead(proxyRes.statusCode, resHeaders);
        clientRes.end(body);
      });
    } else {
      // Pass through binary/non-text responses unchanged (images, fonts, etc.)
      clientRes.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(clientRes);
    }
  });

  proxyReq.on("error", (err) => {
    console.error("[ingress-proxy] upstream error:", err.message);
    if (!clientRes.headersSent) {
      clientRes.writeHead(502);
      clientRes.end("Bad Gateway: Next.js not ready");
    }
  });

  clientReq.pipe(proxyReq);
});

server.listen(LISTEN_PORT, "0.0.0.0", () => {
  console.log(
    `[ingress-proxy] Listening on 0.0.0.0:${LISTEN_PORT} → Next.js :${NEXT_PORT}`,
  );
});
