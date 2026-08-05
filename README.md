# 🦊 FoxBox — Foxes Camera Toolbox

A single-window Windows toolbox for getting photos and videos off camera cards and into an organized library — then culling, deduplicating, shrinking, and color-correcting them (with a special soft spot for scuba photos). Everything lives in one dark-themed app with six tabs.

Supported photo formats: JPG, PNG, HEIC/HEIF, TIFF, and common RAW (CR2/CR3, NEF, ARW, DNG, RAF, ORF).
Supported video formats: MP4, MOV, AVI, MTS/M2TS, MKV, MXF, 3GP, WMV, and Insta360 `.insv`.

## Getting started

1. Install [Python](https://python.org) (3.10+) with "Add to PATH" checked.
2. Double-click `run_ingest.bat` — it installs the two dependencies (Pillow, hachoir) and launches the app.

Or by hand:

```
pip install -r requirements.txt
python camera_ingest.py
```

While any long job is running the app tells Windows not to sleep; normal power settings resume the moment the job finishes.

---

## ▶ Ingest

Copies media off SD cards, renames each file by its capture time (`YYYYMMDDHHMMSS.jpg`), organizes into `YYYY/MM` subfolders, and verifies every copy before optionally deleting the source.

**How to use**

1. **🔌 ADD CARD…** — queue one or more source cards/folders. Queued sources run one after another, and you can add another card *while a run is in progress* (plug in card 2 while card 1 copies; it starts automatically when card 1 finishes). **➖ Remove** drops a selected entry from the queue.
2. Set a **Local USB Destination**, a **Remote Server Destination**, or both. Leave one blank to skip it — at least one is required.
3. Options:
   - **Delete source files after verified copy** — sources are only deleted after every destination has a byte-verified copy.
   - **Organize into YYYY/MM subfolders** — off = everything lands flat in the destination root.
4. **▶ START INGEST**.

**What it does for you**

- Capture time comes from EXIF (photos) or container metadata (videos), falling back to file timestamps. Files with the same second get `_1`, `_2`… suffixes.
- Every copy is verified against the source (SHA256) before the source is touched.
- Exact duplicates on the card (same content, different name) are detected and copied only once.
- Windows read-only attributes (typical for camera files) are cleared automatically so deletes and overwrites don't fail.
- Per-card and grand-total summaries appear in the Activity Log.

---

## 🛡 Safe Delete

Frees up a card you've already ingested: it proves every file on the card exists on your server before deleting anything from the card.

**How to use**

1. Set the **SD Card / Source** and the **File Server to Check** folder.
2. **🔍 SCAN**. Matching runs in phases: filename match first, then content verification, then (with your permission) a full content search of the server for files that were renamed.
3. Review the results table — every row shows the card file and exactly where its server copy lives.
4. **🗑 DELETE MATCHED FROM SD** removes only the confirmed files, after a confirmation dialog.

**Notes**

- Content checks use a fast fingerprint (file size + hashes of the first/middle/last 1 MB) rather than reading entire multi-GB files, so scans are quick even for video.
- Server fingerprints are cached in `.camera_ingest_cache.json`, so repeat scans are much faster. **Clear Hash Cache** forces a full re-read.
- Files not found on the server are listed as NOT FOUND and never deleted.

---

## 🖼 Low-Res

Makes Google Photos-friendly low-resolution JPEG copies of a photo folder. Originals are never modified.

**How to use**

1. Pick a **Source Photos Folder** and a **Low-Res Output Folder**.
2. Adjust **Max long edge** (default 2048 px) and **JPEG quality** (default 85) if desired.
3. Options: mirror the subfolder structure, and skip files already converted (so re-runs are incremental).
4. **▶ START CONVERT**.

EXIF data is preserved and orientation is baked in so copies display upright. Videos and unreadable files (e.g. RAW without codec support) are logged and skipped.

---

## 🌱 Weed

A fast keyboard-driven accept/reject culling tool.

**Keys**

| Key | Action |
|---|---|
| ↑ or A | **Accept** — photo stays exactly where it is |
| ↓ or R | **Reject** — moved to a `rejects` subfolder *next to the photo* (date structure preserved) |
| ← or U | **Undo** last accept/reject |
| Scroll wheel | **Zoom** (1×–10×, anchored at the cursor); drag to pan; zoom out to reset |
| F or F11 | **Fullscreen** (hides all chrome) |
| Esc | Exit fullscreen |

**Features**

- **Resume** — progress saves after every action. Reopen the folder later and it offers to continue where you stopped. If you finished a folder and later add new photos, it offers to start at the first *new* photo.
- **Jump to #** — type a photo number in the status-row field (or click Go) to skip anywhere.
- **Up Next filmstrip** — thumbnails of the next 5 photos on the right; click one to jump to it.
- Photos already in a `rejects` folder are excluded from future sessions.
- To finalize a cull, just delete the `rejects` folders (or keep them as an archive).

---

## ♊ Dedup

Finds and removes true duplicate files in a library.

**How to use**

1. Pick a folder and **🔍 SCAN FOR DUPLICATES**.
2. Same-size files are treated as suspects, then verified by content — photos byte-for-byte (SHA256), videos by size + head/tail fingerprint. Same-size-but-different files are never flagged.
3. The table shows each duplicate next to the copy being **kept** (always the oldest). Nothing is deleted until you click **🗑 DELETE DUPLICATES** and confirm; the dialog shows how much space you'll recover.

---

## 🤿 Dive Color

Fixes the muted blue/green cast of underwater photos. Water absorbs red light first; this tool rebuilds it.

**How it works** — each photo gets its own auto-computed LUT: every color channel is stretched back to full range (percentile-clipped, with the red gain capped so deep-water shots don't amplify into noise), followed by a gentle saturation and contrast lift. Because the LUT is computed per photo, shallow reef shots get a light touch while deep blue shots get a stronger rebuild.

**How to use**

1. **👁 PREVIEW A PHOTO…** — pick any dive shot and see before/after side by side. Drag the **Strength** slider (default 80%) and the preview updates live.
2. Set a **Source Photos Folder** and a **Corrected Output Folder** (must differ).
3. **🤿 CORRECT ALL PHOTOS** — writes quality-92 JPEG copies mirroring your folder structure, EXIF preserved. Originals are never modified.

Photos in `rejects` folders are ignored (weed first, then correct only the keepers). Already-corrected files are skipped on re-runs. The batch runs in parallel across all CPU cores.

---

## Files the app creates

| File | Purpose |
|---|---|
| `.camera_ingest_cache.json` | Server fingerprint cache for Safe Delete |
| `.weed_sessions.json` | Per-folder Weed progress for resume |
| `rejects/` subfolders | Created by Weed next to rejected photos |

All are safe to delete — you only lose cached speed or resume position.
