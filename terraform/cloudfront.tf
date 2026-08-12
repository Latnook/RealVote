resource "aws_cloudfront_origin_access_control" "s3" {
  name                              = "${var.project}-s3"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# /api/items is identical for every visitor and never sets a cookie, so it can be
# shared — but only if the cookie is kept OUT of the cache key.
resource "aws_cloudfront_cache_policy" "api_items" {
  name        = "${var.project}-api-items"
  default_ttl = 30
  min_ttl     = 0
  max_ttl     = 60

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
  }
}

resource "aws_cloudfront_function" "dir_index" {
  name    = "${var.project}-dir-index"
  runtime = "cloudfront-js-2.0"
  comment = "Redirect extensionless URIs to a trailing slash, then append index.html; S3 origins have no directory index."
  publish = true
  code    = <<-JS
    function handler(event) {
      var req = event.request;
      // Extensionless and slashless (e.g. "/admin") means a directory: send the
      // browser to the canonical trailing-slash URL. Three guards, all load-bearing:
      //   1. /^\/[^/\\]/ — the path must start with exactly ONE slash. "//evil.com/x"
      //      would otherwise yield a protocol-relative Location and redirect visitors
      //      off our own domain; the backslash is excluded because some browsers
      //      normalize "/\evil.com/x" the same way.
      //   2. no trailing slash — those are handled by the index.html rewrite below.
      //   3. the dot test — "/admin/config.json" has a dot, so it is never rewritten
      //      and still 404s when absent. If that path ever returned HTML, admin.js
      //      would boot LOCAL mode and the panel would have NO authentication at all.
      // Known and accepted: the Location drops any query string. No link on the site
      // uses one on an extensionless path, and rebuilding it here is disproportionate.
      if (/^\/[^/\\]/.test(req.uri) && !req.uri.endsWith("/") && !req.uri.split("/").pop().includes(".")) {
        return {
          statusCode: 301,
          statusDescription: "Moved Permanently",
          headers: { location: { value: req.uri + "/" } }
        };
      }
      if (req.uri.endsWith("/")) {
        req.uri += "index.html";
      }
      return req;
    }
  JS
}

locals {
  # The site loads nothing it does not serve itself: no CDN, no webfont, no analytics.
  # That makes `default-src 'none'` plus a handful of 'self' directives achievable —
  # and with no 'unsafe-inline' anywhere, an injected <script> or style attribute is
  # inert even if an esc() call is ever missed. Keeping it that way is a constraint on
  # future edits: inline styles and inline <script> will silently stop working.
  csp_site = join(" ", [
    "default-src 'none';",
    "script-src 'self';",
    "style-src 'self';",
    "img-src 'self';",
    "connect-src 'self';",
    "base-uri 'none';",
    "form-action 'none';",
    "frame-ancestors 'none';",
    "object-src 'none'",
  ])

  # The admin panel needs three things the public site does not:
  #   connect-src https: — the create form fetches an operator-typed picture URL from
  #     any host (admin.js urlToBlob), signs in against cognito-idp.<region>.amazonaws.com,
  #     and PUTs the converted image to a presigned S3 URL. All three are cross-origin.
  #   img-src blob:/data: — canvas-converted WebP previews.
  #   form-action 'self' — the login and create <form>s are submit-handled in JS, but a
  #     browser still evaluates the directive before preventDefault() runs.
  # script-src stays 'self': the Cognito SDK is vendored under /admin/vendor/, and its
  # `new Function("return this")` fallback is unreachable in any browser with globalThis,
  # so no 'unsafe-eval' is needed.
  csp_admin = join(" ", [
    "default-src 'none';",
    "script-src 'self';",
    "style-src 'self';",
    "img-src 'self' data: blob:;",
    "connect-src 'self' https:;",
    "base-uri 'none';",
    "form-action 'self';",
    "frame-ancestors 'none';",
    "object-src 'none'",
  ])
}

# Attached to the HTML/CSS/JS behaviours. HSTS is one year with includeSubDomains but
# NOT preload: preloading is effectively irreversible and commits every latnook.com
# subdomain, which is a decision beyond this project.
resource "aws_cloudfront_response_headers_policy" "site" {
  name = "${var.project}-site"
  security_headers_config {
    content_security_policy {
      content_security_policy = local.csp_site
      override                = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY" # frame-ancestors already covers this; belt for pre-CSP browsers
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = false
      override                   = true
    }
  }
}

resource "aws_cloudfront_response_headers_policy" "admin" {
  name = "${var.project}-admin"
  security_headers_config {
    content_security_policy {
      content_security_policy = local.csp_admin
      override                = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "no-referrer" # never leak the admin URL to a picture's host
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = false
      override                   = true
    }
  }

  # index.html already carries <meta name="robots">, but that is invisible to a crawler
  # fetching admin.js or config.json directly.
  custom_headers_config {
    items {
      header   = "X-Robots-Tag"
      value    = "noindex, nofollow"
      override = true
    }
  }
}

# JSON responses render nothing, so they need no full CSP — just transport hardening
# and a refusal to be framed or sniffed into another content type.
resource "aws_cloudfront_response_headers_policy" "api" {
  name = "${var.project}-api"
  security_headers_config {
    content_security_policy {
      content_security_policy = "default-src 'none'; frame-ancestors 'none'"
      override                = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "no-referrer"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = false
      override                   = true
    }
  }
}

# `sandbox` puts a directly-opened picture in an opaque origin, so an SVG that slipped
# past scripts/add-image.py's sanitiser still cannot touch this origin's cookies or DOM.
resource "aws_cloudfront_response_headers_policy" "img" {
  name = "${var.project}-img"
  security_headers_config {
    content_type_options {
      override = true
    }
    content_security_policy {
      content_security_policy = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; sandbox"
      override                = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "no-referrer"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = false
      override                   = true
    }
  }
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = [var.domain_name]
  price_class         = "PriceClass_100"
  comment             = "RealVote"

  origin {
    origin_id                = "s3"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
  }

  origin {
    origin_id   = "api"
    domain_name = replace(aws_apigatewayv2_api.main.api_endpoint, "https://", "")
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id           = "s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.site.id
    compress                   = true

    # S3 origins have no directory index, so /admin/ would 404 on the key "admin/"
    # without this. Attached only here and on /admin/* — never on /img/* or /api/* —
    # so it can't rewrite /admin/config.json (no trailing slash) into an index fetch;
    # that path must still 404 when absent.
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.dir_index.arn
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/img/*"
    target_origin_id           = "s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6"
    response_headers_policy_id = aws_cloudfront_response_headers_policy.img.id
    compress                   = true
  }

  ordered_cache_behavior {
    path_pattern               = "/api/items"
    target_origin_id           = "api"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.api_items.id
    origin_request_policy_id   = "59781a5b-3903-41f3-afcb-af62929ccde1" # Managed-CORS-CustomOrigin
    response_headers_policy_id = aws_cloudfront_response_headers_policy.api.id
    compress                   = true
  }

  # Every other API path is per-visitor: forward cookies, cache nothing.
  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "api"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled
    origin_request_policy_id   = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # Managed-AllViewerExceptHostHeader
    response_headers_policy_id = aws_cloudfront_response_headers_policy.api.id
    compress                   = true
  }

  # Split out from the default behaviour purely to carry its own headers policy: the
  # admin panel needs a looser connect-src than the public site (see local.csp_admin)
  # and must not hand that relaxation to every visitor. Caching is unchanged — same
  # managed policy as the default behaviour — and dir_index has to be re-attached here,
  # or /admin/ would resolve to the S3 key "admin/" and 404. Declared LAST because the
  # ordered behaviours are precedence-ordered and these four patterns are disjoint:
  # appending leaves the existing three at their current indexes, so the plan reads as
  # one added behaviour rather than a shuffle of all four.
  ordered_cache_behavior {
    path_pattern               = "/admin/*"
    target_origin_id           = "s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.admin.id
    compress                   = true

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.dir_index.arn
    }
  }

  # NOTE: no custom_error_response for 403/404. Rewriting them to index.html would make
  # /admin/config.json return a 200 HTML page, and the admin would boot LOCAL mode in
  # production. Missing objects must stay missing.

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}
