#!/usr/bin/env python3
"""
Aggiunge ai PLANNING di AniList i sequel (anche solo annunciati o in corso)
degli anime che hai segnato come COMPLETED.

Uso:
    python anilist_sequels.py --dry-run     # mostra cosa farebbe, senza modificare nulla
    python anilist_sequels.py               # aggiunge davvero ai Planning

Opzioni utili:
    --include-finished   considera anche i sequel gia' finiti (utile per recuperare
                         stagioni che ti sei perso)
    --formats TV,MOVIE   formati ammessi (default: TV,TV_SHORT,MOVIE,ONA)
"""

import argparse
import os
import sys
import time

import requests

API_URL = "https://graphql.anilist.co"

VIEWER_QUERY = """
query { Viewer { id name } }
"""

LIST_QUERY = """
query ($userId: Int, $chunk: Int) {
  MediaListCollection(userId: $userId, type: ANIME, chunk: $chunk, perChunk: 100) {
    hasNextChunk
    lists {
      entries {
        status
        media {
          id
          title { romaji english }
          relations {
            edges {
              relationType
              node {
                id
                type
                format
                status
                title { romaji english }
              }
            }
          }
        }
      }
    }
  }
}
"""

SAVE_MUTATION = """
mutation ($mediaId: Int, $status: MediaListStatus) {
  SaveMediaListEntry(mediaId: $mediaId, status: $status) { id status }
}
"""


def gql(token, query, variables=None):
    """Esegue una query GraphQL gestendo il rate limit di AniList."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    for _ in range(5):
        r = requests.post(
            API_URL,
            json={"query": query, "variables": variables or {}},
            headers=headers,
            timeout=30,
        )
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "30")) + 1
            print(f"  (rate limit, aspetto {wait}s...)")
            time.sleep(wait)
            continue
        if r.status_code != 200:
            sys.exit(f"Errore API {r.status_code}: {r.text[:300]}")
        data = r.json()
        if "errors" in data:
            sys.exit(f"Errore GraphQL: {data['errors']}")
        return data["data"]
    sys.exit("Troppi tentativi falliti (rate limit).")


def title_of(media):
    t = media["title"]
    return t.get("english") or t.get("romaji") or str(media["id"])


def fetch_entries(token, user_id):
    """Scarica tutta la lista anime (tutti gli stati), a blocchi."""
    entries = {}
    chunk = 1
    while True:
        data = gql(token, LIST_QUERY, {"userId": user_id, "chunk": chunk})
        coll = data["MediaListCollection"]
        for lst in coll["lists"]:
            for e in lst["entries"]:
                entries[e["media"]["id"]] = e  # dedup (liste custom)
        if not coll["hasNextChunk"]:
            break
        chunk += 1
        time.sleep(1)
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="non modifica nulla")
    ap.add_argument(
        "--include-finished",
        action="store_true",
        help="includi anche sequel gia' finiti",
    )
    ap.add_argument(
        "--formats",
        default="TV,TV_SHORT,MOVIE,ONA",
        help="formati ammessi, separati da virgola",
    )
    ap.add_argument(
        "--status",
        default="CURRENT",
        choices=["PLANNING", "CURRENT"],
        help="dove aggiungere i sequel: CURRENT (= Watching, default) o PLANNING",
    )
    args = ap.parse_args()

    # Per prendere il token andare all' indirizzo https://anilist.co/settings/developer e creare un client
    # Dopodiche' andare su https://anilist.co/api/v2/oauth/authorize?client_id=IL_TUO_ID&response_type=token sostituisci IL_TUO_ID con quello creato nel link precedente.
    token = os.environ.get("ANILIST_TOKEN")
    if not token:
        sys.exit("Imposta la variabile d'ambiente ANILIST_TOKEN.")

    allowed_formats = {f.strip().upper() for f in args.formats.split(",")}
    allowed_status = {"RELEASING", "NOT_YET_RELEASED"}
    if args.include_finished:
        allowed_status.add("FINISHED")

    viewer = gql(token, VIEWER_QUERY)["Viewer"]
    print(f"Utente: {viewer['name']}")

    entries = fetch_entries(token, viewer["id"])
    on_list = set(entries)  # qualsiasi stato: non tocchiamo cio' che hai gia'
    completed = [e["media"] for e in entries.values() if e["status"] == "COMPLETED"]
    print(f"Anime in lista: {len(on_list)} (completati: {len(completed)})")

    to_add = {}  # id -> (titolo sequel, titolo prequel)
    for media in completed:
        for edge in media["relations"]["edges"]:
            node = edge["node"]
            if edge["relationType"] != "SEQUEL" or node["type"] != "ANIME":
                continue
            if node["id"] in on_list or node["id"] in to_add:
                continue
            if node["format"] not in allowed_formats:
                continue
            if node["status"] not in allowed_status:
                continue
            to_add[node["id"]] = (title_of(node), title_of(media))

    if not to_add:
        print("Nessun sequel da aggiungere.")
        return

    print(f"\nSequel trovati: {len(to_add)}")
    for mid, (seq, prev) in to_add.items():
        print(f"  + {seq}   (sequel di: {prev})")
        print(f"    https://anilist.co/anime/{mid}")

    if args.dry_run:
        print("\n--dry-run: non ho modificato nulla.")
        return

    dest = "Watching" if args.status == "CURRENT" else "Planning"
    print(f"\nAggiungo a {dest}...")
    for mid, (seq, _) in to_add.items():
        gql(token, SAVE_MUTATION, {"mediaId": mid, "status": args.status})
        print(f"  OK  {seq}")
        time.sleep(0.8)
    print("Fatto.")


if __name__ == "__main__":
    main()
