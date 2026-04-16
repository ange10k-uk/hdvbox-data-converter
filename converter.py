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
    1: "FILMIX",
    2: "KINOKONG",
    3: "HDREZKA",
    4: "FS",
}

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
        return int(value)
    except Exception:
        return None


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
    if "rezka" in url or "hdrezka" in url:
        return "HDREZKA"
    if "fs" in url:
        return "FS"

    if filmids_row:
        for key, source_name in [
            ("filmixurl", "FILMIX"),
            ("kinokongurl", "KINOKONG"),
            ("hdrezkaurl", "HDREZKA"),
            ("fsurl", "FS"),
        ]:
            if clean_text(filmids_row.get(key)):
                return source_name

    return "UNKNOWN"


def detect_category(item_row):
    return "FILM"


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
    prefixes = {
        "HDREZKA": "[H]",
        "FILMIX": "[F]",
        "KINOKONG": "[K]",
        "FS": "[FS]",
    }
    prefix = prefixes.get(source)
    if prefix:
        return f"{prefix} - {title}"
    return title


def make_base_item(item_row, filmids_row=None):
    status_text = item_row.get("status") or ""
    source = detect_source(item_row, filmids_row)
    title = build_title(item_row)
    base = {
        "id": str(item_row["_id"]),
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
            return value
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

        for row in app_favorites_rows:
            video_id = row["VIDEO_ID_COL"]
            item = items_by_id.get(video_id, row)
            filmids_row = filmids_by_video.get(video_id)

            obj = make_base_item(item, filmids_row)
            if use_prefixes:
                obj["title"] = format_title_with_prefix(obj["title"], obj["source"])
            obj["addedAt"] = extract_bookmark_created_at(row)

            obj_id = obj["id"]
            if obj_id not in seen_ids:
                seen_ids.add(obj_id)
                bookmarks.append(obj)

    if has_table(conn, "fs_favorites"):
        fs_rows = load_table_as_dicts(conn, """
            SELECT *
            FROM fs_favorites
            ORDER BY _id DESC
        """)

        for row in fs_rows:
            raw_title = clean_text(row.get("name")) or f"Film {row['_id']}"
            obj = {
                "id": str(row["_id"]),
                "title": format_title_with_prefix(raw_title, "FS"),
                "category": "FILM",
                "source": "FS",
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

            if obj["id"] not in seen_ids:
                seen_ids.add(obj["id"])
                bookmarks.append(obj)

    bookmarks.sort(key=lambda x: x.get("addedAt", 0), reverse=True)
    return bookmarks


def export_history(conn, items_by_id, filmids_by_video):
    if not has_table(conn, "history"):
        return []

    history_rows = load_table_as_dicts(conn, """
        SELECT *
        FROM history
        ORDER BY WATCH_DATE_COL DESC, _id DESC
    """)

    by_video_and_file, by_video = build_video_position_maps(conn)
    episodes_index = build_episodes_index(conn)

    result = []

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

        obj["filmId"] = str(video_id)
        obj["lastWatchedAt"] = safe_int(row.get("WATCH_DATE_COL")) or 0

        file_name = clean_text(row.get("FILE_NAME_COL"))
        obj["watchPosition"] = resolve_watch_position(
            video_id,
            file_name,
            by_video_and_file,
            by_video
        )
        obj["duration"] = duration

        season_num = safe_int(row.get("SEASON_COL")) or 0
        episode_rows = episodes_index.get((video_id, season_num, obj["lastWatchedAt"]), [])

        if episode_rows:
            for ep in episode_rows:
                ep_num = safe_int(ep.get("EPISODE_COL"))
                ep_obj = dict(obj)

                if season_num > 0:
                    ep_obj["seasonNum"] = season_num

                if ep_num is not None:
                    ep_obj["episodeNum"] = ep_num

                if season_num > 0 and ep_num is not None:
                    ep_obj["id"] = make_episode_history_id(video_id, season_num, ep_num)
                else:
                    ep_obj["id"] = str(video_id)

                result.append(ep_obj)
        else:
            if season_num > 0:
                obj["seasonNum"] = season_num
            obj["id"] = str(video_id)
            result.append(obj)

    dedup = {}
    for row in result:
        row_id = row["id"]
        prev = dedup.get(row_id)
        if prev is None or row.get("lastWatchedAt", 0) > prev.get("lastWatchedAt", 0):
            dedup[row_id] = row

    history = sorted(
        dedup.values(),
        key=lambda x: x.get("lastWatchedAt", 0),
        reverse=True
    )
    return history


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

    payload = {
        "version": 1,
        "timestamp": int(time.time() * 1000),
        "bookmarks": export_bookmarks(conn, items_by_id, filmids_by_video, section_filters, use_prefixes),
        "history": export_history(conn, items_by_id, filmids_by_video),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.touch()
    
    with out_path.open("w", encoding="utf-8") as f:
        if pretty:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        else:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    return f"Written: {out_path}"


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
