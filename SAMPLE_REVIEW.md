# Ten-app development checkpoint

Run: 23 November 2026. These are agent and verifier outputs, not human gold labels. The full 100-app grounded run is on hold for review.

| App | Verified verdict | Auth methods | Access | Confidence | Human review |
| --- | --- | --- | --- | --- | --- |
| Pipedrive | Unresolved (`could_not_identify`) | API key, OAuth2 | Trial self-serve | Low | Yes |
| Mailchimp | Buildable now | OAuth2, API key, Basic, bearer token | Free self-serve | High | No |
| Firecrawl | Buildable now | OAuth2, API key | Free self-serve | High | No |
| Vercel | Buildable now | Bearer token, API key, OAuth2 | Free self-serve | High | No |
| Asana | Buildable now | OAuth2, API key | Free self-serve | High | No |
| Pinterest | Buildable with outreach | OAuth2 | Trial self-serve | High | No |
| Gladly | Unresolved (`could_not_identify`) | Basic | Unknown | Low | Yes |
| Mermaid CLI | Not applicable | None | Not applicable | High | No |
| Airtable | Buildable now | OAuth2, bearer token | Free self-serve | High | No |
| Brex | Buildable now | Bearer token, OAuth2 | Free self-serve | High | No |

**Human queue: 2/10 apps (20%).**

| App | Research failure | Verifier rejection |
| --- | --- | --- |
| Pipedrive | Targeted research did not produce a valid citation establishing whether production use of the core API requires app review. The verdict remains unresolved. | The verifier found insufficient evidence for `app_review_required`; the consistency check removed `buildable_now` after that field became unknown. Review [Pipedrive API docs](https://developers.pipedrive.com/docs/api/v1) and [marketplace approval docs](https://pipedrive.readme.io/docs/marketplace-app-approval-process) to distinguish core API use from marketplace listing. |
| Gladly | Targeted research did not produce a valid citation for self-serve credential access. The verdict remains unresolved. | The verifier rejected the trial self-serve claim because [Gladly's setup guide](https://help.gladly.com/developer-tutorials/docs/setup-and-testing) says sandbox purchase may require contacting a CSM or Support. The consistency check removed `buildable_now` after access became unknown. |

Pass 3 computed confidence from verifier results and unknown-field counts. The model's confidence field was ignored. All ten final rows passed the program's verbatim citation check; none has `buildable_now` with unknown auth or self-serve access. Mermaid CLI received `auth_methods=[none]` and `self_serve=not_applicable` from the deterministic rule, citing its [official repository](https://github.com/mermaid-js/mermaid-cli).

Local immutable outputs: `data/pass1_sample_dev10_retry2.json`, `data/pass2_sample_dev10_retry2.json`, `data/pass3_sample_dev10_retry2.json`, `data/verifier_log_sample_dev10_retry2.json`, and `data/human_queue_sample_dev10_retry2.json`. They are ignored by Git and remain available in the working directory for review. The first pass and earlier sample revisions remain untouched.
