import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                home_base TEXT,
                favorite_rivers TEXT[],
                preferred_styles TEXT[],
                max_drive_minutes INTEGER DEFAULT 120,
                gear_notes TEXT,
                risk_comfort TEXT DEFAULT 'moderate',
                wading_comfort TEXT DEFAULT 'moderate',
                catch_and_release BOOLEAN DEFAULT true,
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS fishing_logs (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                trip_date DATE NOT NULL DEFAULT CURRENT_DATE,
                river TEXT,
                spot TEXT,
                conditions TEXT,
                flies TEXT,
                fish_caught INTEGER DEFAULT 0,
                notes TEXT,
                ai_summary TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS wiki_entries (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                entry_type TEXT NOT NULL,
                river TEXT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT[],
                confidence TEXT DEFAULT 'personal',
                source TEXT DEFAULT 'user',
                privacy TEXT DEFAULT 'fuzzy',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS wiki_audit_log (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                action TEXT NOT NULL,
                entry_type TEXT,
                entry_id INTEGER,
                proposed_content TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS river_gage_map (
                id SERIAL PRIMARY KEY,
                river_name TEXT NOT NULL UNIQUE,
                usgs_site_id TEXT,
                latitude FLOAT,
                longitude FLOAT,
                tenkara_suitable BOOLEAN DEFAULT false,
                typical_low_cfs FLOAT,
                typical_high_cfs FLOAT,
                notes TEXT
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        _seed_rivers(cur)
        _seed_default_preferences(cur)


def _seed_rivers(cur):
    rivers = [
        ("Deschutes River", "14103000", 44.6365, -121.1871, True, 200, 2000, "Classic Oregon tenkara water. Upper river below Bend fishes best."),
        ("McKenzie River", "14162500", 44.1271, -122.4818, True, 300, 3000, "Famous for dry flies. Clearest water in Oregon."),
        ("Metolius River", "14075000", 44.4774, -121.6310, True, 150, 800, "Spring-fed, consistent flows. Challenging technical fishing."),
        ("Crooked River", "14087400", 44.3052, -120.8364, True, 50, 500, "Tailwater below Bowman Dam. Consistent year-round."),
        ("North Santiam River", "14185000", 44.7751, -122.6016, True, 400, 5000, "Excellent summer tenkara access above Detroit."),
        ("Sandy River", "14137000", 45.4001, -122.2609, True, 500, 8000, "Near Portland. Steelhead and trout."),
        ("North Umpqua River", "14317000", 43.3201, -122.9316, False, 500, 6000, "Fly-only water. Iconic summer steelhead."),
        ("Rogue River", "14361500", 42.4265, -123.3256, False, 1000, 15000, "Major Oregon river. Diverse fishery."),
        ("Wilson River", "14301500", 45.5271, -123.5501, True, 200, 4000, "North coast access. Cutthroat and steelhead."),
        ("Willamette River", "14211720", 45.5231, -122.6765, False, 2000, 50000, "Main stem. Bass, trout, steelhead in tributaries."),
    ]
    for r in rivers:
        cur.execute("""
            INSERT INTO river_gage_map (river_name, usgs_site_id, latitude, longitude,
                tenkara_suitable, typical_low_cfs, typical_high_cfs, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (river_name) DO NOTHING;
        """, r)


def _seed_default_preferences(cur):
    cur.execute("SELECT id FROM preferences WHERE user_id = 'default' LIMIT 1;")
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO preferences (user_id, home_base, favorite_rivers, preferred_styles,
                max_drive_minutes, gear_notes, risk_comfort, wading_comfort, catch_and_release)
            VALUES ('default', 'Bend, OR', ARRAY['Deschutes River', 'Metolius River', 'Crooked River'],
                ARRAY['tenkara', 'dry fly'], 120, '4wt rod, #14-18 dries, tenkara rod', 'moderate', 'moderate', true);
        """)


def get_preferences(user_id="default"):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM preferences WHERE user_id = %s LIMIT 1;", (user_id,))
        return dict(cur.fetchone() or {})


def save_preferences(prefs: dict, user_id="default"):
    with db_cursor() as cur:
        cur.execute("SELECT id FROM preferences WHERE user_id = %s LIMIT 1;", (user_id,))
        existing = cur.fetchone()
        if existing:
            cur.execute("""
                UPDATE preferences SET home_base=%s, favorite_rivers=%s, preferred_styles=%s,
                    max_drive_minutes=%s, gear_notes=%s, risk_comfort=%s, wading_comfort=%s,
                    catch_and_release=%s, updated_at=NOW()
                WHERE user_id=%s;
            """, (prefs.get("home_base"), prefs.get("favorite_rivers", []),
                  prefs.get("preferred_styles", []), prefs.get("max_drive_minutes", 120),
                  prefs.get("gear_notes"), prefs.get("risk_comfort", "moderate"),
                  prefs.get("wading_comfort", "moderate"), prefs.get("catch_and_release", True),
                  user_id))
        else:
            cur.execute("""
                INSERT INTO preferences (user_id, home_base, favorite_rivers, preferred_styles,
                    max_drive_minutes, gear_notes, risk_comfort, wading_comfort, catch_and_release)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (user_id, prefs.get("home_base"), prefs.get("favorite_rivers", []),
                  prefs.get("preferred_styles", []), prefs.get("max_drive_minutes", 120),
                  prefs.get("gear_notes"), prefs.get("risk_comfort", "moderate"),
                  prefs.get("wading_comfort", "moderate"), prefs.get("catch_and_release", True)))


def add_fishing_log(log: dict, user_id="default"):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO fishing_logs (user_id, trip_date, river, spot, conditions, flies,
                fish_caught, notes, ai_summary)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;
        """, (user_id, log.get("trip_date"), log.get("river"), log.get("spot"),
              log.get("conditions"), log.get("flies"), log.get("fish_caught", 0),
              log.get("notes"), log.get("ai_summary")))
        return cur.fetchone()["id"]


def get_fishing_logs(user_id="default", limit=20):
    with db_cursor() as cur:
        cur.execute("""
            SELECT * FROM fishing_logs WHERE user_id = %s
            ORDER BY trip_date DESC LIMIT %s;
        """, (user_id, limit))
        return [dict(r) for r in cur.fetchall()]


def add_wiki_entry(entry: dict, user_id="default"):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO wiki_entries (user_id, entry_type, river, title, content, tags,
                confidence, source, privacy)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;
        """, (user_id, entry.get("entry_type", "spot"), entry.get("river"),
              entry.get("title"), entry.get("content"), entry.get("tags", []),
              entry.get("confidence", "personal"), entry.get("source", "user"),
              entry.get("privacy", "fuzzy")))
        return cur.fetchone()["id"]


def get_wiki_entries(user_id="default", entry_type=None, river=None):
    with db_cursor() as cur:
        q = "SELECT * FROM wiki_entries WHERE user_id = %s"
        params = [user_id]
        if entry_type:
            q += " AND entry_type = %s"
            params.append(entry_type)
        if river:
            q += " AND river ILIKE %s"
            params.append(f"%{river}%")
        q += " ORDER BY updated_at DESC;"
        cur.execute(q, params)
        return [dict(r) for r in cur.fetchall()]


def search_wiki(query: str, user_id="default"):
    with db_cursor() as cur:
        cur.execute("""
            SELECT *, similarity(content || ' ' || title, %s) AS score
            FROM wiki_entries
            WHERE user_id = %s
              AND (content ILIKE %s OR title ILIKE %s OR river ILIKE %s)
            ORDER BY score DESC LIMIT 5;
        """, (query, user_id, f"%{query}%", f"%{query}%", f"%{query}%"))
        return [dict(r) for r in cur.fetchall()]


def get_recent_logs_for_river(river: str, user_id="default", limit=5):
    with db_cursor() as cur:
        cur.execute("""
            SELECT * FROM fishing_logs
            WHERE user_id = %s AND river ILIKE %s
            ORDER BY trip_date DESC LIMIT %s;
        """, (user_id, f"%{river}%", limit))
        return [dict(r) for r in cur.fetchall()]


def get_rivers():
    with db_cursor() as cur:
        cur.execute("SELECT * FROM river_gage_map ORDER BY river_name;")
        return [dict(r) for r in cur.fetchall()]


def save_chat_message(role: str, content: str, user_id="default"):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO chat_history (user_id, role, content) VALUES (%s, %s, %s);
        """, (user_id, role, content))


def get_chat_history(user_id="default", limit=20):
    with db_cursor() as cur:
        cur.execute("""
            SELECT role, content FROM chat_history
            WHERE user_id = %s
            ORDER BY created_at DESC LIMIT %s;
        """, (user_id, limit))
        rows = [dict(r) for r in cur.fetchall()]
        return list(reversed(rows))


def log_audit(action: str, entry_type: str, proposed_content: str, entry_id=None, user_id="default"):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO wiki_audit_log (user_id, action, entry_type, entry_id, proposed_content)
            VALUES (%s, %s, %s, %s, %s);
        """, (user_id, action, entry_type, entry_id, proposed_content))
