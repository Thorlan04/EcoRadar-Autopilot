"""
Module de gestion de base de données SQLite pour EcoRadar-Autopilot.
Gère l'état persistant des communes, historiques de prix, synthèses IA et journaux.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "state.db")


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Initialise les tables de la base de données avec indexes appropriés."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Table des villes suivies
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cities (
                code_insee TEXT PRIMARY KEY,
                nom TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                codes_postaux TEXT NOT NULL,
                departement TEXT,
                region TEXT,
                population INTEGER NOT NULL DEFAULT 0,
                latitude REAL,
                longitude REAL,
                status TEXT NOT NULL DEFAULT 'active',
                date_added TEXT NOT NULL,
                last_updated TEXT,
                consecutive_empty_runs INTEGER DEFAULT 0
            )
        """)
        
        # Table de l'historique des snapshots carburants par ville
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fuel_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_insee TEXT NOT NULL,
                date_ref TEXT NOT NULL,
                station_count INTEGER NOT NULL DEFAULT 0,
                avg_gazole REAL,
                min_gazole REAL,
                avg_sp95 REAL,
                min_sp95 REAL,
                avg_sp98 REAL,
                min_sp98 REAL,
                avg_e10 REAL,
                min_e10 REAL,
                avg_e85 REAL,
                min_e85 REAL,
                avg_gplc REAL,
                min_gplc REAL,
                raw_data_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (code_insee) REFERENCES cities(code_insee)
            )
        """)

        # Table des synthèses SEO et FAQ générées par IA / fallback
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS city_summaries (
                code_insee TEXT PRIMARY KEY,
                date_ref TEXT NOT NULL,
                summary_markdown TEXT NOT NULL,
                faq_json TEXT NOT NULL,
                key_takeaways_json TEXT NOT NULL,
                ai_generated INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (code_insee) REFERENCES cities(code_insee)
            )
        """)

        # Table état Tempo EDF du jour et lendemain
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tempo_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                date_today TEXT NOT NULL,
                couleur_today TEXT NOT NULL,
                lib_today TEXT NOT NULL,
                date_tomorrow TEXT,
                couleur_tomorrow TEXT,
                lib_tomorrow TEXT,
                updated_at TEXT NOT NULL
            )
        """)

        # Table de journalisation et audit d'auto-guérison
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                phase TEXT NOT NULL,
                status TEXT NOT NULL,
                details TEXT
            )
        """)

        # Indexes de performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fuel_insee_date ON fuel_snapshots(code_insee, date_ref)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cities_status ON cities(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cities_slug ON cities(slug)")
        
        conn.commit()


def log_event(phase: str, status: str, details: str = "", db_path: str = DB_PATH) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO execution_logs (timestamp, phase, status, details) VALUES (?, ?, ?, ?)",
            (now_iso, phase, status, details)
        )
        conn.commit()


def upsert_city(city_data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    codes_postaux_str = json.dumps(city_data.get("codesPostaux", []))
    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO cities (
                code_insee, nom, slug, codes_postaux, departement, region, 
                population, latitude, longitude, status, date_added, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code_insee) DO UPDATE SET
                nom = excluded.nom,
                population = excluded.population,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                last_updated = excluded.last_updated
        """, (
            city_data["code"],
            city_data["nom"],
            city_data["slug"],
            codes_postaux_str,
            city_data.get("departement"),
            city_data.get("region"),
            city_data.get("population", 0),
            city_data.get("latitude"),
            city_data.get("longitude"),
            city_data.get("status", "active"),
            city_data.get("date_added", now_iso),
            now_iso
        ))
        conn.commit()


def get_active_cities(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM cities WHERE status = 'active' ORDER BY population DESC"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["codes_postaux"] = json.loads(d["codes_postaux"]) if d["codes_postaux"] else []
            result.append(d)
        return result


def get_city_count(db_path: str = DB_PATH) -> int:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) as count FROM cities WHERE status = 'active'").fetchone()
        return row["count"] if row else 0


def get_all_known_insee_codes(db_path: str = DB_PATH) -> set:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT code_insee FROM cities").fetchall()
        return {r["code_insee"] for r in rows}


def save_fuel_snapshot(code_insee: str, snapshot: Dict[str, Any], stations_list: List[Dict[str, Any]], db_path: str = DB_PATH) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw_json = json.dumps(stations_list, ensure_ascii=False)
    
    with get_connection(db_path) as conn:
        # Met à jour le compteur d'exécutions vides si 0 stations
        station_count = len(stations_list)
        if station_count == 0:
            conn.execute(
                "UPDATE cities SET consecutive_empty_runs = consecutive_empty_runs + 1, last_updated = ? WHERE code_insee = ?",
                (now_iso, code_insee)
            )
        else:
            conn.execute(
                "UPDATE cities SET consecutive_empty_runs = 0, last_updated = ? WHERE code_insee = ?",
                (now_iso, code_insee)
            )
            
        conn.execute("""
            INSERT INTO fuel_snapshots (
                code_insee, date_ref, station_count,
                avg_gazole, min_gazole,
                avg_sp95, min_sp95,
                avg_sp98, min_sp98,
                avg_e10, min_e10,
                avg_e85, min_e85,
                avg_gplc, min_gplc,
                raw_data_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            code_insee,
            today_date,
            station_count,
            snapshot.get("avg_gazole"),
            snapshot.get("min_gazole"),
            snapshot.get("avg_sp95"),
            snapshot.get("min_sp95"),
            snapshot.get("avg_sp98"),
            snapshot.get("min_sp98"),
            snapshot.get("avg_e10"),
            snapshot.get("min_e10"),
            snapshot.get("avg_e85"),
            snapshot.get("min_e85"),
            snapshot.get("avg_gplc"),
            snapshot.get("min_gplc"),
            raw_json,
            now_iso
        ))
        conn.commit()


def get_latest_fuel_snapshot(code_insee: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM fuel_snapshots WHERE code_insee = ? ORDER BY id DESC LIMIT 1",
            (code_insee,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["stations"] = json.loads(d["raw_data_json"]) if d.get("raw_data_json") else []
        return d


def get_fuel_price_trends(code_insee: str, db_path: str = DB_PATH) -> Dict[str, Dict[str, Any]]:
    """Calcule la tendance (variation en centimes et direction) sur les 2 derniers snapshots."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT avg_gazole, avg_sp95, avg_sp98, avg_e10, avg_e85, avg_gplc, created_at FROM fuel_snapshots WHERE code_insee = ? ORDER BY id DESC LIMIT 2",
            (code_insee,)
        ).fetchall()
        
        fuels = ["gazole", "sp95", "sp98", "e10", "e85", "gplc"]
        trends = {}
        
        if len(rows) < 2:
            for f in fuels:
                trends[f] = {"direction": "stable", "diff": 0.0, "text": "Stable"}
            return trends
            
        latest = dict(rows[0])
        previous = dict(rows[1])
        
        for f in fuels:
            key = f"avg_{f}"
            cur = latest.get(key)
            prev = previous.get(key)
            if cur is not None and prev is not None and prev > 0:
                diff = round(cur - prev, 3)
                if diff > 0.005:
                    direction = "hausse"
                    text = f"+{diff:.3f} €/L"
                elif diff < -0.005:
                    direction = "baisse"
                    text = f"{diff:.3f} €/L"
                else:
                    direction = "stable"
                    text = "Stable"
                trends[f] = {"direction": direction, "diff": diff, "text": text}
            else:
                trends[f] = {"direction": "stable", "diff": 0.0, "text": "Stable"}
                
        return trends


def save_city_summary(code_insee: str, summary_md: str, faq_list: List[Dict[str, str]], 
                      takeaways: List[str], ai_generated: bool, db_path: str = DB_PATH) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO city_summaries (
                code_insee, date_ref, summary_markdown, faq_json, key_takeaways_json, ai_generated, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code_insee) DO UPDATE SET
                date_ref = excluded.date_ref,
                summary_markdown = excluded.summary_markdown,
                faq_json = excluded.faq_json,
                key_takeaways_json = excluded.key_takeaways_json,
                ai_generated = excluded.ai_generated,
                updated_at = excluded.updated_at
        """, (
            code_insee,
            today_date,
            summary_md,
            json.dumps(faq_list, ensure_ascii=False),
            json.dumps(takeaways, ensure_ascii=False),
            1 if ai_generated else 0,
            now_iso
        ))
        conn.commit()


def get_city_summary(code_insee: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM city_summaries WHERE code_insee = ?", (code_insee,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["faq"] = json.loads(d["faq_json"]) if d.get("faq_json") else []
        d["takeaways"] = json.loads(d["key_takeaways_json"]) if d.get("key_takeaways_json") else []
        return d


def save_tempo_state(today: Dict[str, Any], tomorrow: Dict[str, Any], db_path: str = DB_PATH) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO tempo_state (
                id, date_today, couleur_today, lib_today,
                date_tomorrow, couleur_tomorrow, lib_tomorrow, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                date_today = excluded.date_today,
                couleur_today = excluded.couleur_today,
                lib_today = excluded.lib_today,
                date_tomorrow = excluded.date_tomorrow,
                couleur_tomorrow = excluded.couleur_tomorrow,
                lib_tomorrow = excluded.lib_tomorrow,
                updated_at = excluded.updated_at
        """, (
            today.get("dateJour", ""),
            today.get("couleur", "BLEU"),
            today.get("libCouleur", "Bleu"),
            tomorrow.get("dateJour", ""),
            tomorrow.get("couleur", "INDETERMINE"),
            tomorrow.get("libCouleur", "Non défini"),
            now_iso
        ))
        conn.commit()


def get_tempo_state(db_path: str = DB_PATH) -> Dict[str, Any]:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM tempo_state WHERE id = 1").fetchone()
        if row:
            return dict(row)
        return {
            "date_today": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "couleur_today": "BLEU",
            "lib_today": "Bleu",
            "date_tomorrow": "",
            "couleur_tomorrow": "BLEU",
            "lib_tomorrow": "Bleu",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }


def get_national_fuel_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """Calcule la moyenne nationale sur l'ensemble des derniers relevés."""
    with get_connection(db_path) as conn:
        row = conn.execute("""
            SELECT 
                AVG(avg_gazole) as nat_avg_gazole, MIN(min_gazole) as nat_min_gazole,
                AVG(avg_sp95) as nat_avg_sp95, MIN(min_sp95) as nat_min_sp95,
                AVG(avg_sp98) as nat_avg_sp98, MIN(min_sp98) as nat_min_sp98,
                AVG(avg_e10) as nat_avg_e10, MIN(min_e10) as nat_min_e10,
                AVG(avg_e85) as nat_avg_e85, MIN(min_e85) as nat_min_e85,
                AVG(avg_gplc) as nat_avg_gplc, MIN(min_gplc) as nat_min_gplc,
                SUM(station_count) as total_stations,
                COUNT(DISTINCT code_insee) as cities_with_data
            FROM fuel_snapshots
            WHERE id IN (
                SELECT MAX(id) FROM fuel_snapshots GROUP BY code_insee
            )
        """).fetchone()
        
        if not row:
            return {}
        return dict(row)


def purge_stale_cities(threshold_runs: int = 5, db_path: str = DB_PATH) -> List[str]:
    """Désactive les villes n'ayant plus aucune station depuis un certain nombre d'exécutions."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT code_insee, nom FROM cities WHERE consecutive_empty_runs >= ? AND status = 'active'",
            (threshold_runs,)
        ).fetchall()
        purged = []
        for r in rows:
            purged.append(f"{r['nom']} ({r['code_insee']})")
            conn.execute("UPDATE cities SET status = 'inactive' WHERE code_insee = ?", (r["code_insee"],))
        conn.commit()
        return purged
