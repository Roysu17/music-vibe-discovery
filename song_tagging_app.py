#!/usr/bin/env python3
"""
Interactive song tagging app for building a song database.

Features:
- Pops up a random song suggestion from the internet (iTunes Search API).
- Displays song details: title, artist, album, year, length, genre.
- Tries to fetch internet tags from Last.fm when LASTFM_API_KEY is available.
- Tries to find a YouTube watch link without needing YouTube API keys.
- Lets the user enter/confirm tags and save records to JSON + CSV.

Run:
    python song_tagging_app.py
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Any
import csv
import json
import os
import random
import re
import urllib.parse
import webbrowser

import requests
import tkinter as tk
from tkinter import messagebox


DB_JSON = Path("song_database.json")
DB_CSV = Path("song_database.csv")


SEARCH_TERMS = [
    "indie",
    "dream pop",
    "shoegaze",
    "punk",
    "rnb",
    "electronic",
    "jazz",
    "hip hop",
    "ambient",
    "folk",
    "garage rock",
    "bedroom pop",
    "dance",
]


@dataclass
class SongRecord:
    title: str
    artist: str
    album: str = ""
    year: str = ""
    length_seconds: int = 0
    bpm: float = 0.0
    camelot: str = ""
    energy: float = 0.0
    added_at: str = ""
    duration_seconds: int = 0
    popularity: int = 0
    genres: List[str] = field(default_factory=list)
    album_date: str = ""
    dance: float = 0.0
    acoustic: float = 0.0
    instrumental: float = 0.0
    valence: float = 0.0
    speech: float = 0.0
    live: float = 0.0
    loud_db: float = 0.0
    musical_key: str = ""
    time_signature: int = 0
    isrc: str = ""
    explicit: bool = False
    genre: str = ""
    internet_tags: List[str] = field(default_factory=list)
    user_tags: List[str] = field(default_factory=list)
    combined_tags: List[str] = field(default_factory=list)
    youtube_url: str = ""
    source_url: str = ""
    itunes_track_id: str = ""
    fetched_at_utc: str = ""


def clean_tag(tag: str) -> str:
    return re.sub(r"\s+", " ", tag.strip().lower())


def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        cleaned = clean_tag(item)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def parse_tags(text: str) -> List[str]:
    if not text.strip():
        return []
    parts = [part.strip() for part in text.split(",")]
    return unique_keep_order(parts)


def format_seconds(seconds: int) -> str:
    if seconds <= 0:
        return "unknown"
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


def load_database(path: Path) -> List[SongRecord]:
    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    records: List[SongRecord] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                try:
                    records.append(SongRecord(**item))
                except TypeError:
                    continue
    return records


def save_database(records: List[SongRecord]) -> None:
    payload = [asdict(record) for record in records]
    DB_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    fieldnames = list(asdict(SongRecord(title="", artist="")).keys())
    with DB_CSV.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for record in records:
            row = asdict(record)
            for key, value in row.items():
                if isinstance(value, list):
                    row[key] = ", ".join(value)
            writer.writerow(row)


def fetch_random_song() -> Optional[Dict[str, str]]:
    term = random.choice(SEARCH_TERMS)
    params = {
        "term": term,
        "entity": "song",
        "limit": 50,
        "country": "US",
    }

    try:
        response = requests.get("https://itunes.apple.com/search", params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return None

    results = data.get("results", [])
    songs = [item for item in results if isinstance(item, dict) and item.get("trackName") and item.get("artistName")]
    if not songs:
        return None

    pick = random.choice(songs)

    release_date = str(pick.get("releaseDate", ""))
    year = release_date[:4] if len(release_date) >= 4 else ""
    length_seconds = int((pick.get("trackTimeMillis") or 0) / 1000)

    explicitness = str(pick.get("trackExplicitness", "")).lower()

    return {
        "title": str(pick.get("trackName", "")),
        "artist": str(pick.get("artistName", "")),
        "album": str(pick.get("collectionName", "")),
        "year": year,
        "length_seconds": length_seconds,
        "genre": str(pick.get("primaryGenreName", "")),
        "source_url": str(pick.get("trackViewUrl", "")),
        "itunes_track_id": str(pick.get("trackId", "")),
        "album_date": year,
        "duration_seconds": length_seconds,
        "explicit": explicitness in {"explicit", "cleaned"},
    }


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, clean_tag(a), clean_tag(b)).ratio()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def estimate_audio_features(bpm: float, genres: List[str], explicit: bool, gain_db: float) -> Dict[str, float]:
    genre_text = " ".join(genres).lower()

    dance = 0.45
    energy = 0.48
    acoustic = 0.28
    instrumental = 0.08
    valence = 0.50
    speech = 0.07
    live = 0.10

    if bpm > 0:
        dance += (min(bpm, 170.0) - 90.0) / 220.0
        energy += (min(bpm, 180.0) - 80.0) / 170.0

    if any(word in genre_text for word in ["dance", "edm", "house", "electro", "pop", "disco"]):
        dance += 0.18
        energy += 0.12

    if any(word in genre_text for word in ["punk", "metal", "hardcore", "rock"]):
        energy += 0.16
        valence -= 0.05

    if any(word in genre_text for word in ["ambient", "classical", "acoustic", "folk", "singer-songwriter"]):
        acoustic += 0.25
        energy -= 0.16

    if any(word in genre_text for word in ["instrumental", "post-rock", "score", "soundtrack"]):
        instrumental += 0.34
        speech -= 0.03

    if any(word in genre_text for word in ["hip hop", "rap", "spoken", "podcast"]):
        speech += 0.23
        dance += 0.07

    if explicit:
        speech += 0.03

    # Deezer provides track gain in dB for many songs; use it when available.
    loud_db = gain_db if gain_db != 0 else -9.5
    if loud_db > -7:
        energy += 0.08
    elif loud_db < -12:
        energy -= 0.07

    return {
        "dance": round(_clamp01(dance), 3),
        "energy": round(_clamp01(energy), 3),
        "acoustic": round(_clamp01(acoustic), 3),
        "instrumental": round(_clamp01(instrumental), 3),
        "valence": round(_clamp01(valence), 3),
        "speech": round(_clamp01(speech), 3),
        "live": round(_clamp01(live), 3),
        "loud_db": round(loud_db, 2),
    }


def fetch_deezer_metadata(artist: str, track: str) -> Dict[str, Any]:
    base = {
        "bpm": 0.0,
        "camelot": "",
        "energy": 0.0,
        "popularity": 0,
        "genres": [],
        "album_date": "",
        "dance": 0.0,
        "acoustic": 0.0,
        "instrumental": 0.0,
        "valence": 0.0,
        "speech": 0.0,
        "live": 0.0,
        "loud_db": 0.0,
        "musical_key": "",
        "time_signature": 0,
        "isrc": "",
        "explicit": False,
        "duration_seconds": 0,
    }

    try:
        query = f'track:"{track}" artist:"{artist}"'
        search = requests.get("https://api.deezer.com/search", params={"q": query}, timeout=15)
        search.raise_for_status()
        search_data = search.json()
    except requests.RequestException:
        return base

    candidates = search_data.get("data", []) if isinstance(search_data, dict) else []
    if not candidates:
        return base

    best = None
    best_score = -1.0
    for item in candidates[:10]:
        if not isinstance(item, dict):
            continue
        t = str(item.get("title", ""))
        a = str((item.get("artist") or {}).get("name", ""))
        score = (_similarity(track, t) * 0.65) + (_similarity(artist, a) * 0.35)
        if score > best_score:
            best_score = score
            best = item

    if not isinstance(best, dict):
        return base

    track_id = best.get("id")
    if not track_id:
        return base

    try:
        detail = requests.get(f"https://api.deezer.com/track/{track_id}", timeout=15)
        detail.raise_for_status()
        track_data = detail.json()
    except requests.RequestException:
        track_data = best

    genres: List[str] = []
    artist_id = (track_data.get("artist") or {}).get("id") if isinstance(track_data, dict) else None
    if artist_id:
        try:
            artist_resp = requests.get(f"https://api.deezer.com/artist/{artist_id}", timeout=15)
            artist_resp.raise_for_status()
            artist_data = artist_resp.json()
            for g in (artist_data.get("genres") or {}).get("data", []):
                if isinstance(g, dict) and g.get("name"):
                    genres.append(str(g.get("name")))
        except requests.RequestException:
            pass

    bpm = float(track_data.get("bpm") or 0.0) if isinstance(track_data, dict) else 0.0
    gain = float(track_data.get("gain") or 0.0) if isinstance(track_data, dict) else 0.0
    explicit = bool(track_data.get("explicit_lyrics", False)) if isinstance(track_data, dict) else False
    audio = estimate_audio_features(bpm=bpm, genres=genres, explicit=explicit, gain_db=gain)

    popularity = int((float(track_data.get("rank") or 0.0) / 10000.0)) if isinstance(track_data, dict) else 0
    popularity = max(0, min(popularity, 100))

    return {
        "bpm": round(bpm, 2),
        "camelot": "",  # Not directly available without Spotify-style key/mode endpoints.
        "energy": audio["energy"],
        "popularity": popularity,
        "genres": unique_keep_order(genres),
        "album_date": str(track_data.get("release_date", "")) if isinstance(track_data, dict) else "",
        "dance": audio["dance"],
        "acoustic": audio["acoustic"],
        "instrumental": audio["instrumental"],
        "valence": audio["valence"],
        "speech": audio["speech"],
        "live": audio["live"],
        "loud_db": audio["loud_db"],
        "musical_key": "",  # Not available from the chosen non-Spotify sources.
        "time_signature": 0,  # Not available from the chosen non-Spotify sources.
        "isrc": str(track_data.get("isrc", "")) if isinstance(track_data, dict) else "",
        "explicit": explicit,
        "duration_seconds": int(track_data.get("duration") or 0) if isinstance(track_data, dict) else 0,
    }


def fetch_lastfm_tags(artist: str, track: str, limit: int = 8) -> List[str]:
    api_key = os.getenv("LASTFM_API_KEY", "").strip()
    if not api_key:
        return []

    params = {
        "method": "track.gettoptags",
        "api_key": api_key,
        "artist": artist,
        "track": track,
        "autocorrect": 1,
        "format": "json",
    }

    try:
        response = requests.get("https://ws.audioscrobbler.com/2.0/", params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return []

    tags = data.get("toptags", {}).get("tag", [])
    out: List[str] = []
    for item in tags[:limit]:
        if isinstance(item, dict) and item.get("name"):
            out.append(str(item["name"]))

    return unique_keep_order(out)


def find_youtube_link(artist: str, track: str) -> str:
    query = f"{artist} {track} official audio"
    encoded = urllib.parse.quote_plus(query)
    search_url = f"https://www.youtube.com/results?search_query={encoded}"

    # Try to resolve a direct video URL via DuckDuckGo HTML search.
    ddg_url = "https://duckduckgo.com/html/"
    try:
        response = requests.get(ddg_url, params={"q": f"site:youtube.com/watch {artist} {track}"}, timeout=15)
        response.raise_for_status()
        html = response.text

        hrefs = re.findall(r'href="([^"]+)"', html)
        for href in hrefs:
            if "youtube.com/watch" in href:
                if href.startswith("//"):
                    href = "https:" + href
                if href.startswith("/"):
                    continue
                return href
    except requests.RequestException:
        pass

    return search_url


class SongTaggingApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Music Vibe Discovery - Song Tagging App")
        self.root.geometry("940x700")

        self.records = load_database(DB_JSON)
        self.current_song: Optional[Dict[str, str]] = None
        self.current_internet_tags: List[str] = []

        self._build_ui()

    def _build_ui(self) -> None:
        frame = tk.Frame(self.root, padx=14, pady=14)
        frame.pack(fill="both", expand=True)

        header = tk.Label(
            frame,
            text="Song Discovery + Manual Tagging",
            font=("Segoe UI", 16, "bold"),
            anchor="w",
        )
        header.pack(fill="x", pady=(0, 10))

        self.status_var = tk.StringVar(value=f"Loaded {len(self.records)} saved songs.")
        status_label = tk.Label(frame, textvariable=self.status_var, fg="#444")
        status_label.pack(fill="x", pady=(0, 10))

        button_row = tk.Frame(frame)
        button_row.pack(fill="x", pady=(0, 12))

        self.next_button = tk.Button(
            button_row,
            text="Pop New Song",
            font=("Segoe UI", 10, "bold"),
            command=self.pop_new_song,
            bg="#1f6feb",
            fg="white",
            padx=12,
            pady=6,
        )
        self.next_button.pack(side="left")

        self.save_button = tk.Button(
            button_row,
            text="Save Song + Tags",
            font=("Segoe UI", 10, "bold"),
            command=self.save_current_song,
            bg="#2da44e",
            fg="white",
            padx=12,
            pady=6,
        )
        self.save_button.pack(side="left", padx=(10, 0))

        details_frame = tk.LabelFrame(frame, text="Song Details", padx=8, pady=8)
        details_frame.pack(fill="both", pady=(0, 10))
        details_frame.configure(height=360)
        details_frame.pack_propagate(False)

        self.details_canvas = tk.Canvas(details_frame, highlightthickness=0)
        details_scroll = tk.Scrollbar(details_frame, orient="vertical", command=self.details_canvas.yview)
        self.details_canvas.configure(yscrollcommand=details_scroll.set)
        self.details_canvas.pack(side="left", fill="both", expand=True)
        details_scroll.pack(side="right", fill="y")

        details_inner = tk.Frame(self.details_canvas)
        self._details_window_id = self.details_canvas.create_window((0, 0), window=details_inner, anchor="nw")
        details_inner.bind("<Configure>", lambda _e: self.details_canvas.configure(scrollregion=self.details_canvas.bbox("all")))
        self.details_canvas.bind(
            "<Configure>",
            lambda e: self.details_canvas.itemconfigure(self._details_window_id, width=e.width),
        )

        self.detail_vars = {
            "title": tk.StringVar(value=""),
            "artist": tk.StringVar(value=""),
            "album": tk.StringVar(value=""),
            "year": tk.StringVar(value=""),
            "length": tk.StringVar(value=""),
            "genre": tk.StringVar(value=""),
            "bpm": tk.StringVar(value=""),
            "camelot": tk.StringVar(value=""),
            "energy": tk.StringVar(value=""),
            "added_at": tk.StringVar(value=""),
            "duration": tk.StringVar(value=""),
            "popularity": tk.StringVar(value=""),
            "genres": tk.StringVar(value=""),
            "album_date": tk.StringVar(value=""),
            "dance": tk.StringVar(value=""),
            "acoustic": tk.StringVar(value=""),
            "instrumental": tk.StringVar(value=""),
            "valence": tk.StringVar(value=""),
            "speech": tk.StringVar(value=""),
            "live": tk.StringVar(value=""),
            "loud_db": tk.StringVar(value=""),
            "musical_key": tk.StringVar(value=""),
            "time_signature": tk.StringVar(value=""),
            "isrc": tk.StringVar(value=""),
            "explicit": tk.StringVar(value=""),
            "youtube": tk.StringVar(value=""),
            "source": tk.StringVar(value=""),
        }

        self._detail_row(details_inner, "Title", self.detail_vars["title"])
        self._detail_row(details_inner, "Artist", self.detail_vars["artist"])
        self._detail_row(details_inner, "Album", self.detail_vars["album"])
        self._detail_row(details_inner, "Year", self.detail_vars["year"])
        self._detail_row(details_inner, "Length", self.detail_vars["length"])
        self._detail_row(details_inner, "Genre", self.detail_vars["genre"])
        self.youtube_link_label = self._detail_link_row(
            details_inner,
            "Internet YouTube Link",
            self.detail_vars["youtube"],
        )
        self.source_link_label = self._detail_link_row(
            details_inner,
            "Source Link",
            self.detail_vars["source"],
        )
        self._detail_row(details_inner, "BPM", self.detail_vars["bpm"])
        self._detail_row(details_inner, "Camelot", self.detail_vars["camelot"])
        self._detail_row(details_inner, "Energy", self.detail_vars["energy"])
        self._detail_row(details_inner, "Added at", self.detail_vars["added_at"])
        self._detail_row(details_inner, "Duration", self.detail_vars["duration"])
        self._detail_row(details_inner, "Popularity", self.detail_vars["popularity"])
        self._detail_row(details_inner, "Genres", self.detail_vars["genres"])
        self._detail_row(details_inner, "Album Date", self.detail_vars["album_date"])
        self._detail_row(details_inner, "Dance", self.detail_vars["dance"])
        self._detail_row(details_inner, "Acoustic", self.detail_vars["acoustic"])
        self._detail_row(details_inner, "Instrumental", self.detail_vars["instrumental"])
        self._detail_row(details_inner, "Valence", self.detail_vars["valence"])
        self._detail_row(details_inner, "Speech", self.detail_vars["speech"])
        self._detail_row(details_inner, "Live", self.detail_vars["live"])
        self._detail_row(details_inner, "Loud (dB)", self.detail_vars["loud_db"])
        self._detail_row(details_inner, "Key", self.detail_vars["musical_key"])
        self._detail_row(details_inner, "Time Signature", self.detail_vars["time_signature"])
        self._detail_row(details_inner, "ISRC", self.detail_vars["isrc"])
        self._detail_row(details_inner, "Explicit", self.detail_vars["explicit"])

        tags_frame = tk.LabelFrame(frame, text="Tags", padx=12, pady=10)
        tags_frame.pack(fill="both", expand=True)

        internet_tags_label = tk.Label(tags_frame, text="Internet tags (auto):")
        internet_tags_label.pack(anchor="w")

        self.internet_tags_var = tk.StringVar(value="")
        tk.Label(tags_frame, textvariable=self.internet_tags_var, fg="#0b5394", wraplength=820, justify="left").pack(
            anchor="w", pady=(4, 10)
        )

        tk.Label(tags_frame, text="Your tags (comma separated):").pack(anchor="w")
        self.user_tags_text = tk.Text(tags_frame, height=4)
        self.user_tags_text.pack(fill="x", pady=(4, 10))

        tk.Label(tags_frame, text="Optional notes:").pack(anchor="w")
        self.notes_text = tk.Text(tags_frame, height=4)
        self.notes_text.pack(fill="x", pady=(4, 0))

    def _detail_row(self, parent: tk.Widget, label: str, value_var: tk.StringVar) -> None:
        row = tk.Frame(parent)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=f"{label}:", width=20, anchor="w", font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(row, textvariable=value_var, anchor="w", justify="left", wraplength=660).pack(side="left", fill="x", expand=True)

    def _detail_link_row(self, parent: tk.Widget, label: str, value_var: tk.StringVar) -> tk.Label:
        row = tk.Frame(parent)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=f"{label}:", width=20, anchor="w", font=("Segoe UI", 10, "bold")).pack(side="left")

        link_label = tk.Label(
            row,
            textvariable=value_var,
            anchor="w",
            justify="left",
            wraplength=660,
            fg="#1a0dab",
            cursor="hand2",
            font=("Segoe UI", 9, "underline"),
        )
        link_label.pack(side="left", fill="x", expand=True)
        link_label.bind("<Button-1>", lambda _event: self._open_url(value_var.get().strip()))
        return link_label

    def _open_url(self, url: str) -> None:
        if url.startswith("http://") or url.startswith("https://"):
            webbrowser.open(url)

    def pop_new_song(self) -> None:
        self.status_var.set("Fetching song from internet...")
        self.root.update_idletasks()

        song = fetch_random_song()
        if not song:
            messagebox.showerror("Fetch failed", "Could not fetch a song. Check internet and try again.")
            self.status_var.set("Failed to fetch a song.")
            return

        title = song["title"]
        artist = song["artist"]
        deezer = fetch_deezer_metadata(artist=artist, track=title)

        # Fill requested metadata from non-Spotify sources where possible.
        song.update(deezer)

        internet_tags = fetch_lastfm_tags(artist=artist, track=title)
        youtube_url = find_youtube_link(artist=artist, track=title)
        song["youtube_url"] = youtube_url
        song["added_at"] = datetime.now(timezone.utc).isoformat()

        if not song.get("album_date"):
            song["album_date"] = song.get("year", "")
        if not song.get("duration_seconds"):
            song["duration_seconds"] = int(song.get("length_seconds", 0) or 0)

        self.current_song = song
        self.current_internet_tags = internet_tags

        self.detail_vars["title"].set(song["title"])
        self.detail_vars["artist"].set(song["artist"])
        self.detail_vars["album"].set(song.get("album", ""))
        self.detail_vars["year"].set(song.get("year", ""))
        self.detail_vars["length"].set(format_seconds(int(song.get("length_seconds", 0) or 0)))
        self.detail_vars["genre"].set(song.get("genre", ""))
        self.detail_vars["bpm"].set(str(song.get("bpm", "")))
        self.detail_vars["camelot"].set(str(song.get("camelot", "")) or "n/a")
        self.detail_vars["energy"].set(str(song.get("energy", "")))
        self.detail_vars["added_at"].set(str(song.get("added_at", "")))
        self.detail_vars["duration"].set(format_seconds(int(song.get("duration_seconds", 0) or 0)))
        self.detail_vars["popularity"].set(str(song.get("popularity", "")))
        self.detail_vars["genres"].set(", ".join(song.get("genres", [])) if isinstance(song.get("genres", []), list) else "")
        self.detail_vars["album_date"].set(str(song.get("album_date", "")))
        self.detail_vars["dance"].set(str(song.get("dance", "")))
        self.detail_vars["acoustic"].set(str(song.get("acoustic", "")))
        self.detail_vars["instrumental"].set(str(song.get("instrumental", "")))
        self.detail_vars["valence"].set(str(song.get("valence", "")))
        self.detail_vars["speech"].set(str(song.get("speech", "")))
        self.detail_vars["live"].set(str(song.get("live", "")))
        self.detail_vars["loud_db"].set(str(song.get("loud_db", "")))
        self.detail_vars["musical_key"].set(str(song.get("musical_key", "")) or "n/a")
        self.detail_vars["time_signature"].set(str(song.get("time_signature", "")) or "n/a")
        self.detail_vars["isrc"].set(str(song.get("isrc", "")) or "n/a")
        self.detail_vars["explicit"].set("yes" if bool(song.get("explicit", False)) else "no")
        self.detail_vars["youtube"].set(song.get("youtube_url", ""))
        self.detail_vars["source"].set(song.get("source_url", ""))
        self._refresh_link_styles()

        if internet_tags:
            self.internet_tags_var.set(", ".join(internet_tags))
        else:
            self.internet_tags_var.set("No internet tags found (set LASTFM_API_KEY for richer tags).")

        self.user_tags_text.delete("1.0", "end")
        self.notes_text.delete("1.0", "end")

        existing = self._find_existing_record(song["itunes_track_id"], song["title"], song["artist"])
        if existing:
            if existing.user_tags:
                self.user_tags_text.insert("1.0", ", ".join(existing.user_tags))
            if existing.combined_tags and not existing.user_tags:
                self.user_tags_text.insert("1.0", ", ".join(existing.combined_tags))
            self.status_var.set("Fetched a song. Existing record found and tags pre-filled.")
        else:
            self.status_var.set("Fetched a new song. Add your tags and save.")

    def _refresh_link_styles(self) -> None:
        for label, key in (
            (self.youtube_link_label, "youtube"),
            (self.source_link_label, "source"),
        ):
            has_url = bool(self.detail_vars[key].get().strip())
            label.configure(fg="#1a0dab" if has_url else "#777")

    def _find_existing_record(self, track_id: str, title: str, artist: str) -> Optional[SongRecord]:
        for rec in self.records:
            if track_id and rec.itunes_track_id and rec.itunes_track_id == track_id:
                return rec
            if clean_tag(rec.title) == clean_tag(title) and clean_tag(rec.artist) == clean_tag(artist):
                return rec
        return None

    def save_current_song(self) -> None:
        if not self.current_song:
            messagebox.showwarning("No song", "Click 'Pop New Song' first.")
            return

        user_tag_text = self.user_tags_text.get("1.0", "end").strip()
        user_tags = parse_tags(user_tag_text)
        combined_tags = unique_keep_order(self.current_internet_tags + user_tags)

        notes = self.notes_text.get("1.0", "end").strip()
        if notes:
            notes_tags = parse_tags(notes.replace("\n", ","))
            combined_tags = unique_keep_order(combined_tags + notes_tags)

        song = self.current_song

        record = SongRecord(
            title=song["title"],
            artist=song["artist"],
            album=song.get("album", ""),
            year=song.get("year", ""),
            length_seconds=int(song.get("length_seconds", 0) or 0),
            bpm=float(song.get("bpm", 0.0) or 0.0),
            camelot=str(song.get("camelot", "")),
            energy=float(song.get("energy", 0.0) or 0.0),
            added_at=str(song.get("added_at", "")),
            duration_seconds=int(song.get("duration_seconds", 0) or 0),
            popularity=int(song.get("popularity", 0) or 0),
            genres=song.get("genres", []) if isinstance(song.get("genres", []), list) else [],
            album_date=str(song.get("album_date", "")),
            dance=float(song.get("dance", 0.0) or 0.0),
            acoustic=float(song.get("acoustic", 0.0) or 0.0),
            instrumental=float(song.get("instrumental", 0.0) or 0.0),
            valence=float(song.get("valence", 0.0) or 0.0),
            speech=float(song.get("speech", 0.0) or 0.0),
            live=float(song.get("live", 0.0) or 0.0),
            loud_db=float(song.get("loud_db", 0.0) or 0.0),
            musical_key=str(song.get("musical_key", "")),
            time_signature=int(song.get("time_signature", 0) or 0),
            isrc=str(song.get("isrc", "")),
            explicit=bool(song.get("explicit", False)),
            genre=song.get("genre", ""),
            internet_tags=self.current_internet_tags,
            user_tags=user_tags,
            combined_tags=combined_tags,
            youtube_url=song.get("youtube_url", ""),
            source_url=song.get("source_url", ""),
            itunes_track_id=song.get("itunes_track_id", ""),
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
        )

        existing = self._find_existing_record(record.itunes_track_id, record.title, record.artist)
        if existing:
            index = self.records.index(existing)
            self.records[index] = record
            action = "updated"
        else:
            self.records.append(record)
            action = "saved"

        save_database(self.records)
        self.status_var.set(f"Song {action}. Database now has {len(self.records)} songs.")
        messagebox.showinfo("Saved", f"Song {action} to {DB_JSON.name} and {DB_CSV.name}.")


def main() -> None:
    root = tk.Tk()
    app = SongTaggingApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
