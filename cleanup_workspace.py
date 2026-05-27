"""
Archive all fact sheets in the LeanIX workspace (for clean test runs).
Archived fact sheets are recoverable for 90 days from LeanIX UI.

Usage:
    python3 cleanup_workspace.py --base-url https://<tenant>.leanix.net --token <api_token>

    # Dry run (only shows what would be archived, no changes):
    python3 cleanup_workspace.py --base-url ... --token ... --dry-run
"""
import argparse
import time
import requests

# Fact sheet types to archive, in reverse dependency order
FS_TYPES = [
    "Initiative",
    "Interface",
    "Application",
    "ITComponent",
    "BusinessCapability",
    "BusinessContext",
    "Organization",
    "DataObject",
    "Platform",
    "Provider",
]

_token_cache = {"token": None, "expires_at": 0}


def _get_bearer(base_url: str, api_token: str) -> str:
    if time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    resp = requests.post(
        f"{base_url}/services/mtm/v1/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": "apitoken", "client_secret": api_token},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return _token_cache["token"]


def _gql(base_url: str, token: str, query: str, variables: dict = None) -> dict:
    for attempt in range(1, 4):
        bearer = _get_bearer(base_url, token)
        resp = requests.post(
            f"{base_url}/services/pathfinder/v1/graphql",
            json={"query": query, "variables": variables or {}},
            headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 2 ** attempt))
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data
    raise RuntimeError("Max retries exceeded")


def get_all_ids(base_url: str, token: str, fs_type: str) -> list[str]:
    """Fetch all fact sheet IDs of a given type."""
    query = """
    query($after: String) {
      allFactSheets(factSheetType: %s, after: $after, first: 100) {
        pageInfo { hasNextPage endCursor }
        edges { node { id displayName } }
      }
    }
    """ % fs_type
    ids = []
    cursor = None
    while True:
        data = _gql(base_url, token, query, {"after": cursor})
        page = data["data"]["allFactSheets"]
        for edge in page["edges"]:
            ids.append((edge["node"]["id"], edge["node"]["displayName"]))
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return ids


ARCHIVE_MUTATION = """
mutation($id: ID!, $rev: Long!, $patches: [Patch]!) {
  updateFactSheet(id: $id, rev: $rev, comment: "Archimedes cleanup", patches: $patches, validateOnly: false) {
    factSheet { id status rev }
  }
}
"""

GET_REV_QUERY = """
query($id: ID!) {
  factSheet(id: $id) { rev }
}
"""

_ARCHIVE_PATCH = [{"op": "replace", "path": "/status", "value": "ARCHIVED"}]


def archive_fact_sheet(base_url: str, token: str, fs_id: str) -> bool:
    try:
        rev_data = _gql(base_url, token, GET_REV_QUERY, {"id": fs_id})
        rev = rev_data["data"]["factSheet"]["rev"]
        _gql(base_url, token, ARCHIVE_MUTATION, {"id": fs_id, "rev": rev, "patches": _ARCHIVE_PATCH})
        return True
    except Exception as exc:
        print(f"    ERROR archiving {fs_id}: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="e.g. https://app.leanix.net")
    parser.add_argument("--token", required=True, help="LeanIX API token")
    parser.add_argument("--dry-run", action="store_true", help="List only, no changes")
    parser.add_argument("--types", nargs="+", help="Only archive these types (default: all)")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    types_to_process = args.types if args.types else FS_TYPES

    total_archived = 0
    for fs_type in types_to_process:
        print(f"\n{fs_type}...")
        ids = get_all_ids(base_url, args.token, fs_type)
        print(f"  Found {len(ids)} fact sheets")
        if args.dry_run:
            for fs_id, name in ids:
                print(f"  [DRY RUN] Would archive: {name} ({fs_id})")
            continue
        for i, (fs_id, name) in enumerate(ids, 1):
            ok = archive_fact_sheet(base_url, args.token, fs_id)
            status = "✓" if ok else "✗"
            print(f"  [{i}/{len(ids)}] {status} {name}")
            if ok:
                total_archived += 1

    if not args.dry_run:
        print(f"\nDone. {total_archived} fact sheets archived.")
    else:
        print("\n[DRY RUN] No changes made.")


if __name__ == "__main__":
    main()
