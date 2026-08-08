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
  comment = "Append index.html to directory URIs; S3 origins have no directory index."
  publish = true
  code    = <<-JS
    function handler(event) {
      var req = event.request;
      if (req.uri.endsWith("/")) {
        req.uri += "index.html";
      }
      return req;
    }
  JS
}

resource "aws_cloudfront_response_headers_policy" "img" {
  name = "${var.project}-img"
  security_headers_config {
    content_type_options {
      override = true
    }
    content_security_policy {
      content_security_policy = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
      override                = true
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
    target_origin_id       = "s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
    compress               = true

    # S3 origins have no directory index, so /admin/ would 404 on the key "admin/"
    # without this. Attached ONLY here — never on /img/* or /api/* — so it can't
    # rewrite /admin/config.json (no trailing slash) into an index fetch; that path
    # must still 404 when absent.
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
    path_pattern             = "/api/items"
    target_origin_id         = "api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = aws_cloudfront_cache_policy.api_items.id
    origin_request_policy_id = "59781a5b-3903-41f3-afcb-af62929ccde1" # Managed-CORS-CustomOrigin
    compress                 = true
  }

  # Every other API path is per-visitor: forward cookies, cache nothing.
  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # Managed-AllViewerExceptHostHeader
    compress                 = true
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
