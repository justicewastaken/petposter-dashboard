"""
fetch_metrics.py — PetPoster Dashboard
Pulls Instagram Graph API metrics for all 4 accounts and writes public/data.json.
Run by GitHub Actions weekly (or manually via workflow_dispatch).
"""

import os
import json
import time
from datetime import datetime, timezone, timedelta

import requests

# ── Account registry ──────────────────────────────────────────────────────────

ACCOUNTS = [
    {
        "slug":       "mochis",
        "username":   "mochis.world.02",
        "display":    "Mochi's World",
        "ig_id":      "17841432038179175",
        "token_env":  "IG_ACCESS_TOKEN",
    },
    {
        "slug":       "frankies",
        "username":   "frankies.world",
        "display":    "Frankie's World",
        "ig_id":      "17841438348725442",
        "token_env":  "IG_ACCESS_TOKEN",
    },
    {
        "slug":       "bobas",
        "username":   "bobasworld.01",
        "display":    "Boba's World",
        "ig_id":      "17841437099435678",
        "token_env":  "IG_ACCESS_TOKEN",
    },
    {
        "slug":       "sunnys",
        "username":   "sunnysworld.01",
        "display":    "Sunny's World",
        "ig_id":      "17841431064559566",
        "token_env":  "IG_ACCESS_TOKEN",
    },
]

BASE = "https://graph.facebook.com/v21.0"
MEDIA_LIMIT = 20   # recent posts to pull per account

# ── Helpers ───────────────────────────────────────────────────────────────────

def get(url, params, label=""):
    resp = requests.get(url, params=params, timeout=20)
    data = resp.json()
    if "error" in data:
        print(f"  ⚠️  {label}: {data['error'].get('message','?')}")
        return None
    return data


def fetch_account_info(ig_id, token):
    fields = "name,username,followers_count,follows_count,media_count,biography,website,profile_picture_url"
    return get(f"{BASE}/{ig_id}", {"fields": fields, "access_token": token}, "account_info")


def fetch_weekly_insights(ig_id, token):
    """
    Account-level insights for the past week.
    Uses 'day' period with since/until to pull 7 days and sum them.
    Falls back gracefully for metrics that aren't available.
    """
    until = int(datetime.now(timezone.utc).timestamp())
    since = until - (7 * 24 * 3600)
    metrics = "reach,impressions,profile_views,website_clicks"
    data = get(
        f"{BASE}/{ig_id}/insights",
        {
            "metric":       metrics,
            "period":       "day",
            "since":        since,
            "until":        until,
            "access_token": token,
        },
        "weekly_insights",
    )
    if not data:
        return {}

    totals = {}
    for item in data.get("data", []):
        name = item["name"]
        total = sum(v["value"] for v in item.get("values", []))
        totals[name] = total
    return totals


def fetch_media_list(ig_id, token):
    fields = "id,caption,timestamp,media_type,like_count,comments_count,permalink,thumbnail_url,media_url"
    data = get(
        f"{BASE}/{ig_id}/media",
        {
            "fields":       fields,
            "limit":        MEDIA_LIMIT,
            "access_token": token,
        },
        "media_list",
    )
    return (data or {}).get("data", [])


def fetch_media_insights(media_id, token):
    """Reel / video metrics. Returns {} on failure."""
    # Reels metrics
    metrics = "plays,reach,saved,shares,comments,likes,total_interactions"
    data = get(
        f"{BASE}/{media_id}/insights",
        {"metric": metrics, "access_token": token},
        f"media/{media_id}",
    )
    if not data:
        return {}
    return {item["name"]: item["values"][0]["value"] if item.get("values") else item.get("value", 0)
            for item in data.get("data", [])}


def fetch_follower_history(ig_id, token, days=28):
    """Daily follower count for the last N days (for trend chart)."""
    until = int(datetime.now(timezone.utc).timestamp())
    since = until - (days * 24 * 3600)
    data = get(
        f"{BASE}/{ig_id}/insights",
        {
            "metric":       "follower_count",
            "period":       "day",
            "since":        since,
            "until":        until,
            "access_token": token,
        },
        "follower_history",
    )
    if not data:
        return []
    for item in data.get("data", []):
        if item["name"] == "follower_count":
            return [{"date": v["end_time"][:10], "value": v["value"]}
                    for v in item.get("values", [])]
    return []


# ── Main ──────────────────────────────────────────────────────────────────────

def build_account_data(acct):
    token = os.environ.get(acct["token_env"], "")
    if not token:
        print(f"  ⚠️  No token found for {acct['username']} (env: {acct['token_env']})")
        return None

    ig_id = acct["ig_id"]
    print(f"\n{'─'*50}")
    print(f"  Fetching @{acct['username']} ({ig_id})")

    info    = fetch_account_info(ig_id, token) or {}
    weekly  = fetch_weekly_insights(ig_id, token)
    history = fetch_follower_history(ig_id, token, days=28)
    media   = fetch_media_list(ig_id, token)

    posts = []
    for m in media:
        time.sleep(0.2)  # gentle rate-limit
        insights = fetch_media_insights(m["id"], token)
        caption = (m.get("caption") or "")[:120]
        posts.append({
            "id":           m["id"],
            "timestamp":    m.get("timestamp", ""),
            "media_type":   m.get("media_type", ""),
            "permalink":    m.get("permalink", ""),
            "thumbnail":    m.get("thumbnail_url") or m.get("media_url", ""),
            "caption":      caption,
            "like_count":   m.get("like_count", 0),
            "comment_count": m.get("comments_count", 0),
            "insights":     insights,
        })

    print(f"  ✅ {len(posts)} posts | followers: {info.get('followers_count','?')}")

    return {
        "slug":          acct["slug"],
        "username":      info.get("username") or acct["username"],
        "display":       acct["display"],
        "ig_id":         ig_id,
        "bio":           info.get("biography", ""),
        "website":       info.get("website", ""),
        "profile_pic":   info.get("profile_picture_url", ""),
        "followers":     info.get("followers_count", 0),
        "follows":       info.get("follows_count", 0),
        "media_count":   info.get("media_count", 0),
        "weekly":        weekly,
        "follower_history": history,
        "posts":         posts,
    }


def main():
    print("PetPoster Dashboard — fetching metrics")
    results = []
    for acct in ACCOUNTS:
        data = build_account_data(acct)
        if data:
            results.append(data)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts":     results,
    }

    out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "data.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Wrote public/data.json — {len(results)} accounts")


if __name__ == "__main__":
    main()
