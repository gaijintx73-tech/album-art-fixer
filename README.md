# Album Art Fixer

A free replacement for the old "Get Album Artwork" button. Finds tracks
missing cover art, looks each album up on Apple's free iTunes Search API
(no account, no API key, no cost), and embeds a 600×600 cover into the file.

## What it does

- Scans a folder of music files (MP3, M4A, FLAC, OGG).
- Skips any file that already has embedded artwork.
- For the rest, reads the artist/album tags, looks the album up on Apple's
  catalog, downloads the cover, and embeds it into the file.
- Prints a summary: fixed / already had art / not found / missing tags.

It never deletes or overwrites your music — it only adds an artwork tag.
Run with `--dry-run` first to see what it would do.

## Usage

```
pip install mutagen requests
python3 album_artwork_fixer.py /path/to/music --dry-run
python3 album_artwork_fixer.py /path/to/music
```

Flags:

- `--dry-run` — report what would happen without changing anything.
- `--force` — replace artwork even on files that already have it.

## iPhone workflow (via iMazing)

If your music lives on an iPhone:

1. **Export:** In iMazing, select your iPhone → Music → export the songs
   to a folder on your computer.
2. **Fix:** Run the script on that folder.
3. **Import back:** In iMazing, drag the fixed files back onto your iPhone's
   Music section (delete the old copies on the phone first to avoid
   duplicates).

Tip: export to a *copy* of your music, not the only copy, until you've
confirmed the results look right on the phone.

## Notes

- Matching is by artist + album tags. If your tags have typos, fix the tags
  first — bad tags are the #1 reason a lookup misses. Re-run afterward;
  the script skips files it already fixed.
- Obscure albums, live bootlegs, and personal recordings won't be in Apple's
  catalog; those get reported as "no artwork found" and are left untouched.
- The script pauses briefly between lookups to stay polite to Apple's API.
  A few hundred songs takes a few minutes.
- Files it can't read are skipped, never modified.
