"""
Generates a synthetic ~30,000-row pipeline (same shape/messiness as the real
sheet) and runs ingest + plan against it, timing both. This is the evidence
for the "still works at 30,000 leads" requirement - not just a claim in the
README.

Run: python tests/scale_test.py
"""
import random
import string
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STAGES = ["new", "New Lead", "contacted", "Contacted ", "Reply", "replied",
          "warm", "Warm", "negotiating", "Call Booked", "ghosted", "no response",
          "lost", "won"]
SOURCES_RESELLER = ["Instagram", "IG", "Whatnot", "Depop", "eBay", "Vinted", "instagram_dm"]
SOURCES_STORE = ["Physical Store", "in-person", "google_maps", "store"]
CITIES = [("London", "UK"), ("Manchester", "UK"), ("Paris", "FR"), ("Berlin", "DE"),
          ("Amsterdam", "NL"), ("New York", "US"), ("LA", "US"), ("Bristol", "UK")]


def rand_word(n=8):
    return "".join(random.choices(string.ascii_lowercase, k=n))


def gen_rows(n, start_id=1):
    rows = []
    for i in range(n):
        lead_id = f"L{start_id + i:06d}"
        is_reseller = random.random() < 0.6
        stage = random.choice(STAGES)
        if is_reseller:
            has_email = random.random() < 0.12  # mirrors the ~12% leak seen in the real data
            rows.append(dict(
                lead_id=lead_id, source=random.choice(SOURCES_RESELLER),
                handle=f"@{rand_word()}", store_name=None, contact_name=None,
                email=f"{rand_word()}@gmail.com" if has_email else None, phone=None,
                city=None, country=None,
                followers=random.randint(100, 60000),
                active_listings=random.randint(5, 500),
                avg_listing_price_gbp=random.randint(5, 70),
                sales_velocity_30d=random.randint(0, 200),
                est_monthly_spend_gbp=random.choice([120, 1500, 9000, "£2,300"]),
                stage=stage, first_seen_date="2026-01-15", last_touch_date="2026-02-10",
                num_touches=random.randint(0, 8), last_inbound_text=None,
                assigned_bdr=random.choice(["Maya", "Tomas", "Priya", None]), notes=None,
            ))
        else:
            city, country = random.choice(CITIES)
            rows.append(dict(
                lead_id=lead_id, source=random.choice(SOURCES_STORE),
                handle=None, store_name=f"{rand_word()} Vintage",
                contact_name=f"{rand_word()} {rand_word()}",
                email=f"shop@{rand_word()}.com", phone=f"+44 7{random.randint(100000000,999999999)}",
                city=city, country=country,
                followers=0, active_listings=None, avg_listing_price_gbp=None,
                sales_velocity_30d=None,
                est_monthly_spend_gbp=random.choice([800, 3000, 5200, "£4,100"]),
                stage=stage, first_seen_date="2026-01-10", last_touch_date="2026-02-05",
                num_touches=random.randint(0, 6), last_inbound_text=None,
                assigned_bdr=random.choice(["Maya", "Tomas", "Priya", None]), notes=None,
            ))
    return rows


def main():
    random.seed(42)
    n = 30000
    print(f"Generating {n} synthetic leads...")
    rows = gen_rows(n)
    df = pd.DataFrame(rows)
    fixture_path = Path("output/scale_fixture.xlsx")
    fixture_path.parent.mkdir(exist_ok=True)
    df.to_excel(fixture_path, sheet_name="pipeline", index=False)

    from src import db, ingest, scoring
    from datetime import date

    db_path = "output/scale_test.db"
    Path(db_path).unlink(missing_ok=True)
    conn = db.connect(db_path)

    t0 = time.time()
    stats = ingest.ingest_batch(conn, str(fixture_path), "pipeline", "scale_test")
    t1 = time.time()
    print(f"Ingest of {n} rows: {t1 - t0:.2f}s -> {stats}")

    t0 = time.time()
    leads = conn.execute("SELECT * FROM leads WHERE stage NOT IN ('won','lost')").fetchall()
    scored = [scoring.score_lead(l, date(2026, 3, 1)) for l in leads]
    t1 = time.time()
    print(f"Scoring of {len(leads)} eligible leads: {t1 - t0:.2f}s")

    total = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
    print(f"Canonical leads after dedup: {total}")
    conn.close()


if __name__ == "__main__":
    main()
