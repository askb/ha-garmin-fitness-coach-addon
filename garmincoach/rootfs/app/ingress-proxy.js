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

function rewriteHtml(html, ingressPath) {
  // Rewrite absolute asset paths
  html = html.replaceAll("/_next/", ingressPath + "/_next/");

  // Rewrite absolute href/src/action attributes
  // Use regex to avoid rewriting protocol-relative URLs (//) and data URIs
  html = html.replaceAll('href="/', 'href="' + ingressPath + "/");
  html = html.replaceAll("href='/", "href='" + ingressPath + "/");
  html = html.replaceAll('src="/', 'src="' + ingressPath + "/");
  html = html.replaceAll("src='/", "src='" + ingressPath + "/");
  html = html.replaceAll('action="/', 'action="' + ingressPath + "/");

  // Fix doubled protocol-relative URLs (href="//..." → was rewritten incorrectly)
  const escaped = ingressPath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const doubledProto = new RegExp(`(href=["']|src=["'])${escaped}//`, "g");
  html = html.replace(doubledProto, "$1//");

  // Inject ingress path into a meta tag so client JS can read it
  html = html.replace(
    "<head>",
    `<head><meta name="ingress-path" content="${ingressPath}">`,
  );

  return html;
}

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

    console.log(
      `[ingress-proxy] ${clientReq.method} ${clientReq.url} → fwd:${forwardPath} → ${proxyRes.statusCode} (${ct.split(";")[0]})`,
    );

    if (isHtml && ingressPath) {
      // Buffer HTML response and rewrite paths
      const chunks = [];
      proxyRes.on("data", (c) => chunks.push(c));
      proxyRes.on("end", () => {
        let html = Buffer.concat(chunks).toString("utf-8");
        html = rewriteHtml(html, ingressPath);

        const resHeaders = { ...proxyRes.headers };
        delete resHeaders["content-length"];
        delete resHeaders["transfer-encoding"];
        resHeaders["content-length"] = Buffer.byteLength(html);

        clientRes.writeHead(proxyRes.statusCode, resHeaders);
        clientRes.end(html);
      });
    } else {
      // Pass through non-HTML responses unchanged
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
