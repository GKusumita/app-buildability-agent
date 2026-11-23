"""Closed research schema and CSV loader."""
from __future__ import annotations

import csv
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parent


class Closed(str, Enum):
    def __str__(self) -> str:
        return self.value


class Category(Closed):
    CRM = "CRM and Sales"
    SUPPORT = "Support and Helpdesk"
    COMMUNICATIONS = "Communications and Messaging"
    MARKETING = "Marketing, Ads, Email and Social"
    ECOMMERCE = "Ecommerce"
    DATA = "Data, SEO and Scraping"
    DEVELOPER = "Developer, Infra and Data platforms"
    PRODUCTIVITY = "Productivity and Project Management"
    FINANCE = "Finance and Fintech"
    AI = "AI Research and Media-native"


class Auth(Closed):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BASIC = "basic"
    BEARER = "bearer_token"
    JWT = "jwt"
    OTHER = "other"
    NONE = "none"
    UNKNOWN = "unknown"


class SelfServe(Closed):
    FREE = "free_self_serve"
    TRIAL = "trial_self_serve"
    PAID = "paid_required"
    ADMIN = "admin_approval"
    PARTNER = "partner_gated"
    SALES = "contact_sales"
    NA = "not_applicable"
    UNKNOWN = "unknown"


class Tri(Closed):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class APIType(Closed):
    REST = "rest"
    GRAPHQL = "graphql"
    SDK = "sdk_only"
    CLI = "cli_only"
    NONE = "none"
    UNKNOWN = "unknown"


class Breadth(Closed):
    BROAD = "broad"
    MODERATE = "moderate"
    NARROW = "narrow"
    UNCLEAR = "unclear"


class Verdict(Closed):
    NOW = "buildable_now"
    OUTREACH = "buildable_with_outreach"
    BLOCKED = "blocked"
    NA = "not_applicable"
    UNIDENTIFIED = "could_not_identify"


class Blocker(Closed):
    NONE = "none"
    PARTNER = "partner_gated"
    PAID = "paid_only"
    NO_API = "no_public_api"
    REVIEW = "app_review"
    ENTERPRISE = "enterprise_only"
    OTHER = "other"


class Confidence(Closed):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceField(Closed):
    AUTH = "auth_methods"
    SERVE = "self_serve"
    API = "api_type"
    VERDICT = "verdict"


class AppInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    name: str
    category: Category
    hint: str


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: EvidenceField
    url: str
    snippet: str

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("evidence URL must be HTTP(S)")
        return value


class AppResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    name: str
    category: Category
    one_liner: str
    auth_methods: list[Auth]
    self_serve: SelfServe
    app_review_required: Tri
    api_type: list[APIType]
    api_breadth: Breadth
    official_mcp: str
    webhooks: Tri
    rate_limits: str
    verdict: Verdict
    blocker: Blocker
    blocker_note: str
    evidence: list[Evidence]
    confidence: Confidence
    notes: str

    @field_validator("one_liner")
    @classmethod
    def one_liner_words(cls, value: str) -> str:
        if len(value.split()) > 20:
            raise ValueError("one_liner exceeds 20 words")
        return value

    @field_validator("notes")
    @classmethod
    def notes_words(cls, value: str) -> str:
        if len(value.split()) > 40:
            raise ValueError("notes exceeds 40 words")
        return value

    @field_validator("official_mcp")
    @classmethod
    def official_mcp_url(cls, value: str) -> str:
        if value in {"none", "unknown"}:
            return value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("official_mcp must be an HTTP(S) URL, none, or unknown")
        return value

    @model_validator(mode="after")
    def basic_consistency(self) -> "AppResult":
        if self.blocker != Blocker.NONE and not self.blocker_note.strip():
            raise ValueError("blocker_note required for a blocker")
        if Auth.UNKNOWN in self.auth_methods and len(self.auth_methods) > 1:
            raise ValueError("unknown auth must stand alone")
        if APIType.UNKNOWN in self.api_type and len(self.api_type) > 1:
            raise ValueError("unknown api_type must stand alone")
        return self


def load_apps(path: Path = ROOT / "apps.csv") -> list[AppInput]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        apps = [AppInput.model_validate(row) for row in csv.DictReader(handle)]
    if len({app.id for app in apps}) != len(apps) or len({app.name for app in apps}) != len(apps):
        raise ValueError("apps.csv contains duplicate IDs or names")
    return apps


def unknown_result(app: AppInput, reason: str) -> AppResult:
    return AppResult(
        id=app.id, name=app.name, category=app.category,
        one_liner="Unknown; usable documentation could not be identified.",
        auth_methods=[Auth.UNKNOWN], self_serve=SelfServe.UNKNOWN,
        app_review_required=Tri.UNKNOWN, api_type=[APIType.UNKNOWN],
        api_breadth=Breadth.UNCLEAR, official_mcp="unknown",
        webhooks=Tri.UNKNOWN, rate_limits="unknown",
        verdict=Verdict.UNIDENTIFIED, blocker=Blocker.NONE,
        blocker_note="", evidence=[], confidence=Confidence.LOW,
        notes=" ".join(reason[:240].split()[:40]),
    )


def check_identity(result: AppResult, app: AppInput) -> None:
    if (result.id, result.name, result.category) != (app.id, app.name, app.category):
        raise ValueError(f"model changed identity for app {app.id}")
