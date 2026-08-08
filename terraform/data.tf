data "aws_caller_identity" "me" {}

# The zone must already exist — this stack never creates or deletes it.
data "aws_route53_zone" "main" {
  name         = "${var.zone_name}."
  private_zone = false
}
