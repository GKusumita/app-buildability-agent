# Verdict rubric

Apply these rules in order; first match wins. Unknowns must remain unknown, and a verdict requires sufficient evidence.

1. Cannot confidently identify the app from name and hint: `could_not_identify`.
2. Open-source CLI/library with no hosted credentials concept: `not_applicable`, `self_serve=not_applicable`, `auth_methods=[none]`.
3. No documented public REST or GraphQL API: `blocked`, `no_public_api`.
4. Credentials require payment with no free tier or trial: `blocked`, `paid_only`.
5. Partnership, contact sales, admin approval, or enterprise plan for API access: `buildable_with_outreach`, `partner_gated` or `enterprise_only` as applicable.
6. Self-serve credentials but production use needs platform app review: `buildable_with_outreach`, `app_review`, `app_review_required=true`.
7. Documented public API and free or trial self-serve credentials: `buildable_now`, `none`.

A free trial or self-serve sandbox counts as self-serve. Ambiguity lowers confidence; it is not permission to guess.
