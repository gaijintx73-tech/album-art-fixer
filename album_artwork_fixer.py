#!/usr/bin/env python3
"""
album_artwork_fixer.py — Find and embed missing album artwork for music files.

Workflow with iMazing:
  1. In iMazing, select your iPhone -> Music -> export the songs to a folder
     on your computer (this folder).
  2. Run this script on that folder. It finds tracks missing embedded
     artwork, looks each album up on Apple's free iTunes Search API, and
     embeds the cover art into the file.
  3. In iMazing, re-import the fixed files back to your iPhone.

Usage:
  python3 album_artwork_fixer.py /path/to/music [--force] [--dry-run]

  --dry-run   Show what would change without modifying any files.
  --force     Replace artwork even on files that already have it.

Requires: pip install mutagen requests
"""

import argparse
import difflib
import os
import sys
import time
import urllib.parse

try:
    import requests
except ImportError:
    sys.exit("Missing 'requests'. Install with: pip install requests")

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import APIC, ID3
    from mutagen.mp4 import MP4Cover
    from mutagen.flac import Picture
except ImportError:
    sys.exit("Missing 'mutagen'. Install with: pip install mutagen")

ITUNES_SEARCH = "https://itunes.apple.com/search"
AUDIO_EXTS = {".mp3", ".m4a", ".mp4", ".flac", ".ogg", ".oga", ".opus"}


def get_tags(path):
    """Return (artist, album, title) from a music file, or (None, None, None)."""
    ext = os.path.splitext(path)[1].lower()
    try:
        audio = MutagenFile(path, easy=True)
    except Exception:
        audio = None
    if audio is not None:
        artist = (audio.get("artist") or [None])[0]
        album = (audio.get("album") or [None])[0]
        title = (audio.get("title") or [None])[0]
        if artist or album or title:
            return artist, album, title
    # Fallback for MP3s whose audio frames won't parse: read ID3 tags directly
    if ext == ".mp3":
        try:
            tags = ID3(path)
            def t(key):
                vals = tags.getall(key)
                return str(vals[0]) if vals else None
            return t("TPE1"), t("TALB"), t("TIT2")
        except Exception:
            pass
    return None, None, None


def has_artwork(path):
    """True if the file already has embedded artwork."""
    ext = os.path.splitext(path)[1].lower()
    try:
        audio = MutagenFile(path)
    except Exception:
        audio = None
    if audio is not None:
        try:
            if ext == ".mp3":
                tags = ID3(path)
                if any(isinstance(tags[k], APIC) for k in tags.keys()):
                    return True
            elif ext in (".m4a", ".mp4"):
                if audio.tags and audio.tags.get("covr"):
                    return True
            elif ext == ".flac":
                if audio.pictures:
                    return True
            elif ext in (".ogg", ".oga", ".opus"):
                if any("metadata_block_picture" in k.lower() for k in (audio.keys() or [])):
                    return True
        except Exception:
            pass
    # Fallback: raw ID3 check for MP3s whose frames won't parse
    if ext == ".mp3":
        try:
            tags = ID3(path)
            return any(isinstance(tags[k], APIC) for k in tags.keys())
        except Exception:
            pass
    return False


def best_album_match(results, album):
    """Pick the iTunes result whose collection name best matches the album."""
    if not results:
        return None
    if not album:
        return results[0]
    names = [r.get("collectionName", "") for r in results]
    match = difflib.get_close_matches(album, names, n=1, cutoff=0.6)
    if match:
        return results[names.index(match[0])]
    return results[0]


def lookup_artwork(artist, album, title):
    """Return high-res artwork bytes via the iTunes Search API, or None."""
    queries = []
    if artist and album:
        queries.append((f"{artist} {album}", "album"))
    if artist and title:
        queries.append((f"{artist} {title}", "song"))
    if album:
        queries.append((album, "album"))

    for term, entity in queries:
        try:
            resp = requests.get(
                ITUNES_SEARCH,
                params={"term": term, "entity": entity, "limit": 5},
                timeout=15,
            )
            data = resp.json()
        except Exception:
            continue
        results = data.get("results", [])
        if not results:
            continue
        pick = best_album_match(results, album) if entity == "album" else results[0]
        art_url = pick.get("artworkUrl100")
        if not art_url:
            continue
        # 100x100 -> 600x600 (600px art always exists on Apple's CDN)
        hi_res = art_url.replace("100x100bb.jpg", "600x600bb.jpg")
        try:
            img = requests.get(hi_res, timeout=20)
            if img.status_code == 200 and img.content[:4] in (
                b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\x89PNG",
                b"\xff\xd8\xff\xdb",
            ):
                return img.content, pick.get("collectionName", "")
        except Exception:
            continue
        time.sleep(0.3)
    return None, None


def embed_artwork(path, image_bytes):
    """Embed JPEG/PNG bytes into the music file. Returns True on success."""
    ext = os.path.splitext(path)[1].lower()
    mime = "image/png" if image_bytes[:4] == b"\x89PNG" else "image/jpeg"
    try:
        if ext == ".mp3":
            tags = ID3(path)
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=image_bytes))
            tags.save(v2_version=3)
        elif ext in (".m4a", ".mp4"):
            audio = MutagenFile(path)
            fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            audio.tags["covr"] = [MP4Cover(image_bytes, imageformat=fmt)]
            audio.save()
        elif ext == ".flac":
            audio = MutagenFile(path)
            audio.clear_pictures()
            pic = Picture()
            pic.type = 3
            pic.mime = mime
            pic.desc = "Cover"
            pic.data = image_bytes
            audio.add_picture(pic)
            audio.save()
        elif ext in (".ogg", ".oga", ".opus"):
            from mutagen.flac import Picture as FlacPicture
            import base64
            audio = MutagenFile(path)
            pic = FlacPicture()
            pic.type = 3
            pic.mime = mime
            pic.desc = "Cover"
            pic.data = image_bytes
            audio["metadata_block_picture"] = base64.b64encode(pic.write()).decode("ascii")
            audio.save()
        else:
            return False
        return True
    except Exception as e:
        print(f"    ! embed failed: {e}")
        return False


def main():
    ap = argparse.ArgumentParser(description="Embed missing album artwork into music files.")
    ap.add_argument("folder", help="Folder of music files exported from iMazing")
    ap.add_argument("--dry-run", action="store_true", help="Report only; change nothing")
    ap.add_argument("--force", action="store_true", help="Replace existing artwork too")
    args = ap.parse_args()

    if not os.path.isdir(args.folder):
        sys.exit(f"Not a folder: {args.folder}")

    files = []
    for root, _, names in os.walk(args.folder):
        for n in names:
            if os.path.splitext(n)[1].lower() in AUDIO_EXTS:
                files.append(os.path.join(root, n))
    files.sort()

    print(f"Found {len(files)} audio files under {args.folder}")
    if args.dry_run:
        print("(dry run — no files will be modified)\n")

    stats = {"fixed": 0, "already": 0, "not_found": 0, "no_tags": 0, "failed": 0}

    for i, path in enumerate(files, 1):
        name = os.path.relpath(path, args.folder)
        if has_artwork(path) and not args.force:
            stats["already"] += 1
            continue
        artist, album, title = get_tags(path)
        if not album and not title:
            print(f"[{i}/{len(files)}] SKIP (no tags): {name}")
            stats["no_tags"] += 1
            continue
        label = f"{artist} — {album}" if artist and album else (album or title)
        print(f"[{i}/{len(files)}] {label}")
        if args.dry_run:
            print("    would look up artwork")
            continue
        image_bytes, matched_album = lookup_artwork(artist, album, title)
        if not image_bytes:
            print("    x no artwork found")
            stats["not_found"] += 1
            continue
        if matched_album and album and matched_album.lower() != album.lower():
            print(f'    ~ matched "{matched_album}"')
        if embed_artwork(path, image_bytes):
            print("    + artwork embedded")
            stats["fixed"] += 1
        else:
            stats["failed"] += 1
        time.sleep(0.5)  # be polite to the API

    print("\nDone.")
    print(f"  Fixed:               {stats['fixed']}")
    print(f"  Already had artwork: {stats['already']}")
    print(f"  No artwork found:    {stats['not_found']}")
    print(f"  Missing tags:        {stats['no_tags']}")
    print(f"  Failed:              {stats['failed']}")
    if stats["not_found"]:
        print("\nTip: for 'no artwork found' tracks, check the artist/album tags for typos,")
        print("then re-run — the script skips files that already have artwork.")


if __name__ == "__main__":
    main()
