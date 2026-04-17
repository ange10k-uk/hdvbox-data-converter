#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
converter.py

Конвертация bookmarks (favorites) и history из SQLite в JSON-формат.

Что поддерживает:
- bookmarks + history
- формат history 1:1 с id вида filmId_sX_eY
- duration в миллисекундах
- watchPosition:
    1) по (VIDEO_ID_COL, FILE_NAME_COL)
    2) fallback по VIDEO_ID_COL
- фильтр bookmarks по section
- множественный выбор section:
    --favorites-section favorites forlater
- all отключает фильтр:
    --favorites-section all

Пример:
    python converter.py db.sqlite export.json --pretty
    python converter.py db.sqlite export.json --favorites-section favorites forlater
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path


SOURCE_MAP = {
    4: "ZONA",
    6: "FILMIX",
    7: "fx2",
    10: "VideoFrame",
    11: "kinolive",
    13: "bigfilm",
    15: "Кинопоиск",
    17: "Seasonvar",
    19: "kodik",
    20: "hdvbalancer",
    21: "zombie film",
    22: "emule",
    23: "VideoCDN",
    25: "simpsonsua",
    26: "uakinoclub",
    27: "bazon",
    28: "ustore",
    29: "Alloha.TV",
    31: "rutor.org",
    32: "fast-torrent",
    33: "Толока",
    34: "yohoho",
    35: "tparser",
    36: "FILMIX",
    37: "RARBG",
    38: "YTS",
    39: "torlook",
    40: "REZKA",
    41: "Кинозал.ТВ",
    42: "cdnmovies",
    43: "namba",
    44: "FilmoZavr",
    53: "IMDB",
    54: "kinorium",
    62: "Tortuga",
    63: "AshDi",
    64: "Lookbase",
    65: "proton",
    90: "YouTube",
    91: "netflix",
    92: "google play",
    93: "megogo",
    94: "sweet.tv",
    95: "Jackett",
    # Jackett
    3920: "Jackett (rutor.org)",
    3921: "Jackett (RuTracker.org)",
    3922: "Jackett (Толока)",
    3923: "Jackett (NNM-Club)",
    3924: "Jackett (Кинозал.ТВ)",
    3925: "Jackett (BitRu)",
    3926: "Jackett (MegaPeer)",
    3927: "Jackett (seleZen)",
    3928: "Jackett (Torrent.by)",
    3929: "Jackett (LostFilm.TV)",
    3930: "Jackett (REZKA)",
    3931: "Jackett (AniLibria)",
    3932: "Jackett (Animelayer)",
    3933: "Jackett (BaibaKoTV)",
    # Torlook
    3902: "torlook (rutor)",
    3904: "torlook (nnm-club)",
    3906: "torlook (rutracker)",
    3908: "torlook (toloka)",
    3909: "torlook (underverse)",
    3910: "torlook (kinozal)",
    3911: "torlook (torrent.by)",
    3912: "torlook (1337x)",
    3913: "torlook (piratebay)",
    3914: "torlook (katcr)",
    3915: "torlook (rarbg)",
}

ALLOWED_BOOKMARK_SOURCES = {"FILMIX", "REZKA", "ZONA", "KINOKONG"}

SECTION_FILTERS = {
    "all": None,
    "favorites": "favorites",
    "forlater": "forlater",
    "finished": "finished",
    "inprocess": "inprocess",
}

BOOKMARK_DATE_COLUMNS = [
    "addedAt", "added_at", "createdAt", "created_at",
    "create_date", "created", "date_created", "timestamp", "updated"
]


def safe_int(value):
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except:
        return None


def to_ms(timestamp):
    """Ensures timestamp is in milliseconds."""
    if not timestamp:
        return 0
    ts = int(timestamp)
    # If it's likely seconds (less than 10 billion), convert to ms
    if ts < 10000000000:
        return ts * 1000
    return ts


def safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def clean_text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def load_table_as_dicts(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(query, params)
    return [dict(row) for row in cur.fetchall()]


def has_table(conn, table_name):
    cur = conn.cursor()
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()
    return row is not None


def detect_source(item_row, filmids_row=None):
    source_id = item_row.get("SOURCE_ID_COL")
    if source_id in SOURCE_MAP:
        return SOURCE_MAP[source_id]

    url = (item_row.get("url") or "").lower()
    if "kinokong" in url:
        return "KINOKONG"
    if "filmix" in url:
        return "FILMIX"
    if "rezka" in url or "hdrezka" in url or "rezkify" in url:
        return "REZKA"
    if "fs.life" in url or "fsgate" in url:
        return "ZONA"

    if filmids_row:
        for key, source_name in [
            ("filmixurl", "FILMIX"),
            ("kinokongurl", "KINOKONG"),
            ("hdrezkaurl", "REZKA"),
            ("fsurl", "ZONA"),
        ]:
            if clean_text(filmids_row.get(key)):
                return source_name

    return "UNKNOWN"


def detect_category(item_row):
    # The database has an explicit is_serial column
    is_serial = safe_int(item_row.get("is_serial"))
    if is_serial is not None:
        return "SERIAL" if is_serial == 1 else "FILM"

    # Fallback to secondary indicators if is_serial is missing
    seasons = safe_int(item_row.get("seasons"))
    if seasons and seasons > 0:
        return "SERIAL"
    
    # ext = str(item_row.get("extname", "")).lower()
    # if "сериал" in ext or "tv series" in ext:
    #     return "SERIAL"

    return "FILM"


def extract_episode_info(file_name):
    """
    Attempts to extract season and episode from filename patterns.
    Patterns:
    - 123456#3#8 -> S3, E8
    - ep_s3e8 -> S3, E8
    - S01E05 -> S1, E5
    """
    if not file_name:
        return None, None
    
    # Pattern: id#S#E (common in Rezka/HDVideoBox)
    match1 = re.search(r"\d+#(\d+)#(\d+)", file_name)
    if match1:
        return int(match1.group(1)), int(match1.group(2))
        
    # Pattern: ep_s3e8
    match2 = re.search(r"ep_s(\d+)e(\d+)", file_name.lower())
    if match2:
        return int(match2.group(1)), int(match2.group(2))
        
    # Pattern: 40_82709_1_1_1 -> ?_?_?_S_E  OR  1145353_718_1_1 -> ?_?_S_E
    # Rezka often uses 4-5 numeric parts separated by underscores
    parts = file_name.split('_')
    if len(parts) >= 4 and all(p.isdigit() for p in parts):
        return int(parts[-2]), int(parts[-1])
        
    # Pattern: S01E05
    match3 = re.search(r"s(\d+)e(\d+)", file_name.lower())
    if match3:
        return int(match3.group(1)), int(match3.group(2))
        
    return None, None


def extract_rezka_slug(item_row, filmids_row=None):
    """
    Extracts the slug from HDRezka URLs.
    Example: .../28704-novobranec-2018-latest.html -> 28704-novobranec-2018-latest
    """
    urls = [
        item_row.get("url"),
        filmids_row.get("hdrezkaurl") if filmids_row else None
    ]

    for url in urls:
        if not url:
            continue
        # Match the last part before .html
        match = re.search(r"/([^/]+)\.html", str(url))
        if match:
            return match.group(1)
    return None


def extract_filmix_slug(item_row, filmids_row=None):
    """
    Extracts the slug from Filmix URLs.
    Example: .../128517-v-novobranets-freee-2018.html -> 128517-v-novobranets-freee-2018.html
    """
    urls = [
        item_row.get("url"),
        filmids_row.get("filmixurl") if filmids_row else None
    ]

    for url in urls:
        if not url:
            continue
        # Match the last part including .html
        match = re.search(r"/([^/]+\.html)", str(url))
        if match:
            return match.group(1)
    return None


def parse_year(value):
    if value is None:
        return None
    text = str(value)
    m = re.search(r"(19|20)\d{2}", text)
    return int(m.group(0)) if m else None


def parse_numeric_from_status(status_text, names):
    if not status_text:
        return None

    for name in names:
        patterns = [
            rf'"{re.escape(name)}"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
            rf"{re.escape(name)}\s*=\s*([0-9]+(?:\.[0-9]+)?)",
            rf"{re.escape(name)}\s*:\s*([0-9]+(?:\.[0-9]+)?)",
        ]
        for pattern in patterns:
            m = re.search(pattern, status_text, flags=re.IGNORECASE)
            if m:
                return safe_float(m.group(1))
    return None


def parse_duration_ms(item_row):
    """
    duration в JSON должен быть в миллисекундах.
    Предполагается, что найденное значение в status хранится в минутах.
    """
    status_text = item_row.get("status") or ""

    value = parse_numeric_from_status(
        status_text,
        [
            "duration", "durationMin", "durationMinutes",
            "runtime", "runtimeMin", "runningTime", "time"
        ]
    )
    if value is None:
        return 0

    minutes = float(value)
    return int(round(minutes * 60 * 1000))


def build_title(item_row):
    return clean_text(item_row.get("name")) or f"Film {item_row['_id']}"


def build_title_original(item_row):
    ext = clean_text(item_row.get("extname"))
    title = clean_text(item_row.get("name"))
    if ext and ext != title:
        return ext
    return None


def format_title_with_prefix(title, source):
    if not source:
        return title
        
    source_lower = source.lower()
    prefixes = {
        "rezka": "[H]",
        "filmix": "[F]",
        "kinokong": "[K]",
        "zona": "[Z]",
    }
    
    # Try direct match or prefix match for Jackett/torlook
    prefix = prefixes.get(source_lower)
    if not prefix:
        for key, val in prefixes.items():
            if key in source_lower:
                prefix = val
                break
                
    if prefix:
        return f"{prefix} - {title}"
    return title


def make_base_item(item_row, filmids_row=None):
    status_text = item_row.get("status") or ""
    source = detect_source(item_row, filmids_row)
    title = build_title(item_row)
    
    item_id = str(item_row["_id"])
    if source == "REZKA":
        slug = extract_rezka_slug(item_row, filmids_row)
        if slug:
            item_id = slug
    elif source == "FILMIX":
        slug = extract_filmix_slug(item_row, filmids_row)
        if slug:
            item_id = slug

    base = {
        "id": item_id,
        "title": title,
        "category": detect_category(item_row),
        "source": source,
    }

    title_original = build_title_original(item_row)
    if title_original:
        base["titleOriginal"] = title_original

    year = parse_year(item_row.get("years"))
    if year is not None:
        base["year"] = year

    poster = clean_text(item_row.get("poster"))
    if poster:
        base["posterUrl"] = poster

    rating_kp = parse_numeric_from_status(
        status_text,
        ["ratingKp", "kp", "kinopoisk", "rating_kp"]
    )
    if rating_kp is not None:
        base["ratingKp"] = rating_kp

    rating_imdb = parse_numeric_from_status(
        status_text,
        ["ratingImdb", "imdb", "rating_imdb"]
    )
    if rating_imdb is not None:
        base["ratingImdb"] = rating_imdb

    return base


def extract_bookmark_created_at(row):
    """
    addedAt = дата создания закладки.
    Если поле в таблице отсутствует, возвращается 0.
    """
    for key in BOOKMARK_DATE_COLUMNS:
        value = safe_int(row.get(key))
        if value is not None and value > 0:
            return to_ms(value)
    return int(time.time() * 1000)


def make_episode_history_id(film_id, season_num, episode_num):
    return f"{film_id}_s{season_num}_e{episode_num}"


def build_video_position_maps(conn):
    """
    Возвращает два индекса:
    1. by_video_and_file[(video_id, file_name)] = max(position)
    2. by_video[video_id] = max(position)
    """
    if not has_table(conn, "video_position"):
        return {}, {}

    rows = load_table_as_dicts(conn, "SELECT * FROM video_position")
    by_video_and_file = {}
    by_video = {}

    for row in rows:
        video_id = row.get("VIDEO_ID_COL")
        file_name = clean_text(row.get("FILE_NAME_COL"))
        pos = safe_int(row.get("POSITION_COL")) or 0

        key = (video_id, file_name)
        existing_specific = by_video_and_file.get(key, 0)
        if pos > existing_specific:
            by_video_and_file[key] = pos

        existing_common = by_video.get(video_id, 0)
        if pos > existing_common:
            by_video[video_id] = pos

    return by_video_and_file, by_video


def resolve_watch_position(video_id, file_name, by_video_and_file, by_video):
    """
    Приоритет:
    1. (video_id, file_name)
    2. video_id
    3. 0
    """
    specific = by_video_and_file.get((video_id, file_name))
    if specific is not None:
        return specific

    common = by_video.get(video_id)
    if common is not None:
        return common

    return 0


def build_episodes_index(conn):
    if not has_table(conn, "episodes"):
        return {}

    rows = load_table_as_dicts(conn, """
        SELECT *
        FROM episodes
        ORDER BY WATCH_DATE_COL DESC, _id DESC
    """)

    index = {}
    for row in rows:
        video_id = row.get("VIDEO_ID_COL")
        season = safe_int(row.get("SEASON_COL")) or 0
        watch_date = safe_int(row.get("WATCH_DATE_COL")) or 0

        key = (video_id, season, watch_date)
        index.setdefault(key, []).append(row)

    return index


def normalize_section_filter(selected_sections):
    if not selected_sections:
        return None
    lowered = [s.lower() for s in selected_sections]
    if "all" in lowered:
        return None
    return [SECTION_FILTERS[s] for s in lowered]


def export_bookmarks(conn, items_by_id, filmids_by_video, section_filters, use_prefixes=False):
    bookmarks = []
    seen_ids = set()
    stats = {
        "total": 0,
        "converted": 0,
        "skipped_source": 0,
        "skipped_duplicate": 0,
        "skipped_sources_breakdown": {}
    }

    if has_table(conn, "app_favorites"):
        query = """
            SELECT af.*, i.*
            FROM app_favorites af
            JOIN items i ON i._id = af.VIDEO_ID_COL
        """
        params = []

        if section_filters is not None:
            placeholders = ",".join(["?"] * len(section_filters))
            query += f" WHERE lower(coalesce(af.section, '')) IN ({placeholders})"
            params.extend(section_filters)

        query += " ORDER BY af._id DESC"

        app_favorites_rows = load_table_as_dicts(conn, query, tuple(params))
        stats["total"] += len(app_favorites_rows)

        for row in app_favorites_rows:
            video_id = row["VIDEO_ID_COL"]
            item = items_by_id.get(video_id, row)
            filmids_row = filmids_by_video.get(video_id)

            obj = make_base_item(item, filmids_row)
            if use_prefixes:
                obj["title"] = format_title_with_prefix(obj["title"], obj["source"])
            obj["addedAt"] = extract_bookmark_created_at(row)

            obj_id = obj["id"]
            if obj_id in seen_ids:
                stats["skipped_duplicate"] += 1
                continue
            
            if obj["source"] not in ALLOWED_BOOKMARK_SOURCES:
                stats["skipped_source"] += 1
                src_name = obj["source"] or "UNKNOWN"
                stats["skipped_sources_breakdown"][src_name] = stats["skipped_sources_breakdown"].get(src_name, 0) + 1
                continue
                
            seen_ids.add(obj_id)
            bookmarks.append(obj)
            stats["converted"] += 1

    if has_table(conn, "fs_favorites"):
        fs_rows = load_table_as_dicts(conn, """
            SELECT *
            FROM fs_favorites
            ORDER BY _id DESC
        """)
        stats["total"] += len(fs_rows)

        for row in fs_rows:
            raw_title = clean_text(row.get("name")) or f"Film {row['_id']}"
            obj = {
                "id": str(row["_id"]),
                "title": format_title_with_prefix(raw_title, "ZONA"),
                "category": "FILM",
                "source": "ZONA",
                "addedAt": extract_bookmark_created_at(row),
            }

            title_original = clean_text(row.get("extname"))
            if title_original and title_original != obj["title"]:
                obj["titleOriginal"] = title_original

            year = parse_year(row.get("years"))
            if year is not None:
                obj["year"] = year

            poster = clean_text(row.get("poster"))
            if poster:
                obj["posterUrl"] = poster

            obj_id = obj["id"]
            if obj_id in seen_ids:
                stats["skipped_duplicate"] += 1
                continue
                
            if obj["source"] not in ALLOWED_BOOKMARK_SOURCES:
                stats["skipped_source"] += 1
                src_name = obj["source"] or "UNKNOWN"
                stats["skipped_sources_breakdown"][src_name] = stats["skipped_sources_breakdown"].get(src_name, 0) + 1
                continue

            seen_ids.add(obj_id)
            bookmarks.append(obj)
            stats["converted"] += 1

    bookmarks.sort(key=lambda x: x.get("addedAt", 0), reverse=True)
    return {"list": bookmarks, "stats": stats}


def export_history(conn, items_by_id, filmids_by_video):
    if not has_table(conn, "history"):
        return {"list": [], "stats": {"total": 0, "converted": 0, "deduplicated": 0}}

    history_rows = load_table_as_dicts(conn, """
        SELECT *
        FROM history
        ORDER BY WATCH_DATE_COL DESC, _id DESC
    """)

    by_video_and_file, by_video = build_video_position_maps(conn)
    episodes_index = build_episodes_index(conn)

    result = []
    total_raw = len(history_rows)

    for row in history_rows:
        video_id = row.get("VIDEO_ID_COL")
        item = items_by_id.get(video_id)
        filmids_row = filmids_by_video.get(video_id)

        if item:
            obj = make_base_item(item, filmids_row)
            duration = parse_duration_ms(item)
        else:
            source = SOURCE_MAP.get(row.get("SOURCE_ID_COL"), "UNKNOWN")
            raw_title = f"Film {video_id}"
            obj = {
                "id": str(video_id),
                "title": raw_title,
                "category": "FILM",
                "source": source,
            }
            duration = 0

        obj["filmId"] = obj["id"]
        obj["lastWatchedAt"] = to_ms(safe_int(row.get("WATCH_DATE_COL")))

        file_name = clean_text(row.get("FILE_NAME_COL"))
        obj["watchPosition"] = resolve_watch_position(
            video_id,
            file_name,
            by_video_and_file,
            by_video
        )
        obj["duration"] = duration

        season_num = safe_int(row.get("SEASON_COL")) or 0
        file_name = clean_text(row.get("FILE_NAME_COL"))
        
        # Try to extract episode info from filename (more reliable than join)
        f_season, f_episode = extract_episode_info(file_name)
        
        # Use filename info if available, otherwise fallback to index join
        actual_season = f_season if f_season else season_num
        ep_num = f_episode
        
        if ep_num is None:
            # Fallback to the indices join if filename parsing failed
            episode_rows = episodes_index.get((video_id, actual_season, obj["lastWatchedAt"]), [])
            if episode_rows:
                ep_num = safe_int(episode_rows[0].get("EPISODE_COL"))

        if ep_num is not None:
            obj["episodeNum"] = ep_num
            if actual_season > 0:
                obj["seasonNum"] = actual_season
                obj["id"] = make_episode_history_id(obj["id"], actual_season, ep_num)
            else:
                # No season but has episode? Just keep original ID or handle as needed
                pass
        elif actual_season > 0:
            obj["seasonNum"] = actual_season
            # Note: We don't change the ID if we don't have an episode number
        
        result.append(obj)

    # Deduplication logic: Unify entries for the same content and timestamp
    # We prioritize the "best" ID (one with an episode suffix) if multiple exist for same time.
    dedup = {}
    for row in result:
        # We group by filmId and timestamp. If multiple exist, we prefer the one with a more specific ID.
        key = (row.get("filmId"), row.get("lastWatchedAt", 0))
        prev = dedup.get(key)
        
        # Priority:
        # 1. Row has episode and prev doesn't
        # 2. Row is newer (if timestamps aren't identical)
        if prev is None:
            dedup[key] = row
            continue
            
        has_ep = "episodeNum" in row
        prev_has_ep = "episodeNum" in prev
        
        if has_ep and not prev_has_ep:
            dedup[key] = row
        elif not has_ep and prev_has_ep:
            pass # Keep previous
        else:
            # Both have ep or both don't: keep the one with larger ID length or just the current
            if len(str(row["id"])) > len(str(prev["id"])):
                dedup[key] = row

    history = sorted(
        dedup.values(),
        key=lambda x: x.get("lastWatchedAt", 0),
        reverse=True
    )
    
    stats = {
        "total": total_raw,
        "converted": len(history),
        "deduplicated": total_raw - len(history)
    }
    
    return {"list": history, "stats": stats}


def process_export(db_path_str, out_path_str, pretty=False, favorites_section=None, use_prefixes=False):
    if favorites_section is None:
        favorites_section = ["all"]

    db_path = Path(db_path_str)
    out_path = Path(out_path_str)

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    if not has_table(conn, "items"):
        raise ValueError("Table 'items' not found")

    items_rows = load_table_as_dicts(conn, "SELECT * FROM items")
    items_by_id = {row["_id"]: row for row in items_rows}

    filmids_by_video = {}
    if has_table(conn, "filmids"):
        filmids_rows = load_table_as_dicts(conn, "SELECT * FROM filmids")
        filmids_by_video = {row["VIDEO_ID_COL"]: row for row in filmids_rows}

    section_filters = normalize_section_filter(favorites_section)

    bookmarks_data = export_bookmarks(conn, items_by_id, filmids_by_video, section_filters, use_prefixes)
    history_data = export_history(conn, items_by_id, filmids_by_video)

    payload = {
        "version": 1,
        "timestamp": int(time.time() * 1000),
        "bookmarks": bookmarks_data["list"],
        "history": history_data["list"],
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.touch()
    
    with out_path.open("w", encoding="utf-8") as f:
        if pretty:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        else:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    # Prepare summary
    bm_stats = bookmarks_data["stats"]
    hi_stats = history_data["stats"]
    
    summary = []
    summary.append("-" * 40)
    summary.append(f"CONVERSION SUMMARY:")
    summary.append("-" * 40)
    summary.append(f"BOOKMARKS:")
    summary.append(f"  Total in DB:      {bm_stats['total']}")
    summary.append(f"  Converted:       {bm_stats['converted']}")
    if bm_stats['skipped_duplicate'] > 0:
        summary.append(f"  Duplicates:      {bm_stats['skipped_duplicate']}")
    if bm_stats['skipped_source'] > 0:
        summary.append(f"  Skipped Sources: {bm_stats['skipped_source']}")
        for src, count in sorted(bm_stats['skipped_sources_breakdown'].items()):
            summary.append(f"    - {src}: {count} (not supported in bookmarks)")
            
    summary.append(f"HISTORY:")
    summary.append(f"  Total in DB:      {hi_stats['total']}")
    summary.append(f"  Converted:       {hi_stats['converted']}")
    if hi_stats['deduplicated'] > 0:
        summary.append(f"  Deduplicated:    {hi_stats['deduplicated']} entries combined")
    summary.append("-" * 40)
    summary.append(f"Output: {out_path.name}")
    
    return "\n".join(summary)


def main():
    parser = argparse.ArgumentParser(description="Convert SQLite favorites/history to exact JSON format")
    parser.add_argument("input_db", help="Path to input sqlite database")
    parser.add_argument("output_json", help="Path to output json file")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument("--use-prefixes", action="store_true", help="Add source prefixes to bookmark titles")

    parser.add_argument(
        "--favorites-section",
        "--favourites-section",
        nargs="+",
        default=["all"],
        choices=list(SECTION_FILTERS.keys()),
        help="Filter favourites by section: all, favorites, forlater, finished, inprocess",
    )
    args = parser.parse_args()

    try:
        msg = process_export(
            args.input_db, 
            args.output_json, 
            pretty=args.pretty, 
            favorites_section=args.favorites_section,
            use_prefixes=args.use_prefixes
        )
        print(msg)
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__" and sys.platform != "emscripten":
    main()
