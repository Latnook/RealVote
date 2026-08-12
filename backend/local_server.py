"""Local dev server: /api/* → lambda_handler (synthesized API GW v2 events),
everything else → static files from ../site. NOT for production."""
import json
import os
import pathlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from app.handler import lambda_handler

SITE_DIR = pathlib.Path(__file__).resolve().parent.parent / "site"

# Mirrors the two CloudFront response headers policies in terraform/cloudfront.tf so a
# CSP violation shows up here rather than in production. Kept in sync by hand — if you
# change one of local.csp_site / local.csp_admin, change the twin here too. HSTS is
# deliberately absent: dev is plain http, where browsers ignore it anyway.
CSP_SITE = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'; object-src 'none'"
)
CSP_ADMIN = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data: blob:; connect-src 'self' https:; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE_DIR), **kwargs)

    def end_headers(self):
        path = self.path.split("?")[0]
        if not path.startswith("/api/"):
            self.send_header(
                "Content-Security-Policy",
                CSP_ADMIN if path.startswith("/admin/") else CSP_SITE,
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        super().end_headers()

    def _api(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length).decode() if length else None
        cookies = []
        if self.headers.get("cookie"):
            cookies = [c.strip() for c in self.headers["cookie"].split(";")]
        event = {
            "rawPath": self.path.split("?")[0],
            "requestContext": {"http": {"method": self.command}},
            "cookies": cookies,
        }
        if body is not None:
            event["body"] = body
            event["isBase64Encoded"] = False
        resp = lambda_handler(event, None)
        payload = resp["body"].encode()
        self.send_response(resp["statusCode"])
        for k, v in resp.get("headers", {}).items():
            self.send_header(k, v)
        for c in resp.get("cookies", []):
            # local http:// can't set Secure cookies — strip the flag for dev only
            self.send_header("Set-Cookie", c.replace("; Secure", ""))
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _maybe_api(self, fallback):
        if self.path.split("?")[0].startswith("/api/"):
            self._api()
        else:
            fallback()

    def do_GET(self):
        self._maybe_api(super().do_GET)

    def do_POST(self):
        self._maybe_api(lambda: self.send_error(405))

    def do_PATCH(self):
        self._maybe_api(lambda: self.send_error(405))


def _lan_ip():
    """Best-effort LAN address, for printing a URL a phone can reach."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 80))  # no packets sent; just picks the default route
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    # Loopback by default. HOST=0.0.0.0 exposes the site to the LAN — and with
    # ALLOW_ADMIN=1 that means an unauthenticated admin API, so only do it on a
    # network you trust.
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"http://localhost:{port}  (site from {SITE_DIR}, /api/* → lambda_handler)")
    if host not in ("127.0.0.1", "localhost"):
        ip = _lan_ip()
        if ip:
            print(f"http://{ip}:{port}  ← from other devices on this network")
        if os.environ.get("ALLOW_ADMIN") == "1":
            print("WARNING: ALLOW_ADMIN=1 and bound beyond loopback — /admin/ is open to the LAN.")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
