variable "region" {
  description = "Region for every regional resource."
  type        = string
  default     = "il-central-1"
}

variable "domain_name" {
  description = "Public hostname for the site."
  type        = string
  default     = "realvote.latnook.com"
}

variable "zone_name" {
  description = "Existing Route53 public hosted zone. Looked up, never created."
  type        = string
  default     = "latnook.com"
}

variable "alarm_email" {
  description = "Address that receives 5xx and billing alarms. Confirm the SNS subscription email after the first apply."
  type        = string
}

variable "admin_email" {
  description = "Email of the single Cognito admin user; the temporary password is sent here."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Estimated-charges alarm threshold in USD."
  type        = number
  default     = 10
}

variable "project" {
  description = "Name prefix for resources."
  type        = string
  default     = "realvote"
}
