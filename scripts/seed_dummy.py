"""Seed data DUMMY untuk demo dashboard.

Semua baris diberi penanda agar mudah dihapus:
  events.payload.dummy = true, product_catalog.tags berisi 'dummy',
  research_interactions.viewer_hash / trust_surveys.respondent_code diawali 'dummy-'.

Jalankan dari folder repo:
  docker compose exec -T dashboard python scripts/seed_dummy.py          # hapus dummy lama + isi ulang
  docker compose exec -T dashboard python scripts/seed_dummy.py --clean  # hapus dummy saja
"""
import os, sys, json, math, random
from datetime import datetime, timedelta, timezone
import psycopg

random.seed(42)
DB = os.environ["DATABASE_URL"]

PRODUCTS = [
    ("Tas Ransel", 289000, "Tas ransel laptop 15 inci, bahan kanvas anti air", ["tas", "ransel", "laptop", "kuliah"]),
    ("Tas Selempang", 159000, "Tas selempang kecil untuk harian, banyak kompartemen", ["tas", "selempang", "harian"]),
    ("Tote Bag", 99000, "Tote bag kanvas tebal, muat A4", ["tas", "tote", "kanvas"]),
    ("Kaos Polos", 69000, "Kaos cotton combed 30s, tersedia S-XXL", ["baju", "kaos", "cotton", "casual"]),
    ("Hoodie Oversize", 219000, "Hoodie fleece oversize, hangat dan lembut", ["baju", "hoodie", "oversize"]),
    ("Kemeja Flanel", 179000, "Kemeja flanel kotak-kotak lengan panjang", ["kemeja", "flanel", "casual"]),
    ("Kemeja Linen", 199000, "Kemeja linen adem untuk kerja dan acara santai", ["kemeja", "linen", "kerja", "adem"]),
    ("Kemeja Batik", 249000, "Kemeja batik modern slim fit", ["kemeja", "batik", "formal"]),
    ("Sepatu Running", 459000, "Sepatu lari ringan dengan cushioning empuk", ["sepatu", "running", "jogging", "cushioning"]),
    ("Sneakers Putih", 379000, "Sneakers kulit sintetis warna putih, cocok semua outfit", ["sepatu", "sneakers", "casual"]),
    ("Sandal Slide", 89000, "Sandal slide karet empuk anti slip", ["sandal", "santai"]),
    ("Celana Chino", 189000, "Celana chino stretch slim fit", ["celana", "chino", "kerja"]),
    ("Jaket Bomber", 329000, "Jaket bomber parasut dengan lapisan dalam", ["jaket", "bomber", "outerwear"]),
    ("Hijab Voal", 59000, "Hijab segi empat voal motif, mudah dibentuk", ["hijab", "voal", "muslimah"]),
    ("Topi Baseball", 79000, "Topi baseball katun dengan strap adjustable", ["topi", "aksesoris"]),
    ("Dompet Kulit", 149000, "Dompet kulit sapi asli, slim", ["dompet", "kulit", "aksesoris"]),
    ("Jam Tangan Sport", 399000, "Jam tangan digital sport tahan air 50m", ["jam", "sport", "aksesoris"]),
]
# bobot popularitas produk (makin besar makin sering disebut)
WEIGHTS = [9, 5, 3, 8, 7, 6, 5, 3, 10, 8, 2, 4, 5, 6, 2, 3, 4]

QUESTION = ["{p} ready size M?", "harga {p} berapa kak?", "{p} ada warna hitam?", "{p} bisa COD?",
            "kapan restock {p}?", "ukuran {p} ada yang XL?", "{p} bahannya apa kak?", "{p} ada promo?"]
POSITIVE = ["{p} bagus banget, suka!", "mantap {p} nya keren", "udah beli {p}, kualitasnya bagus",
            "{p} menarik, mau checkout", "suka sama {p} warna navy"]
NEGATIVE = ["{p} agak mahal ya", "kemarin beli {p} kecewa, jahitan lepas", "{p} nya kok nggak ada size L"]
NEUTRAL = ["checkout {p} 2 pcs", "lagi cari {p} buat kerja", "spill {p} dong", "keep {p} 1 kak",
           "{p} yang kemarin live masih?", "mau lihat {p} lebih dekat"]
NAMES = ["rina", "dewi", "budi", "sari", "agus", "nina", "putri", "andi", "lia", "fajar", "maya", "rizky",
         "tika", "dimas", "wulan", "yoga", "intan", "bayu", "citra", "eko"]
REGIONS = [("DKI Jakarta", 22), ("Jawa Barat", 20), ("Jawa Timur", 15), ("Jawa Tengah", 11), ("Banten", 8),
           ("Sumatera Utara", 6), ("Sulawesi Selatan", 5), ("DI Yogyakarta", 5), ("Bali", 4), ("Kalimantan Timur", 4)]
N_SURVEY = 60
PLATFORMS = [("tiktok", 55), ("shopee", 35), ("instagram", 10)]


def pick(pairs):
    return random.choices([x[0] for x in pairs], [x[1] for x in pairs])[0]


def activity(ts):
    """Faktor ramai 0..1 berdasarkan jam WIB: puncak siang & malam."""
    h = (ts.hour + 7) % 24 + ts.minute / 60
    return max(0.05, 0.55 * math.exp(-((h - 12.5) ** 2) / 4) + 1.0 * math.exp(-((h - 20) ** 2) / 5))


def clean(conn):
    conn.execute("DELETE FROM events WHERE payload->>'dummy'='true'")
    conn.execute("DELETE FROM research_interactions WHERE viewer_hash LIKE 'dummy-%'")
    conn.execute("DELETE FROM trust_surveys WHERE respondent_code LIKE 'dummy-%'")
    conn.execute("DELETE FROM product_catalog WHERE 'dummy' = ANY(tags)")


def seed(conn):
    for name, price, desc, tags in PRODUCTS:
        conn.execute("INSERT INTO product_catalog(name,price,description,tags,stock) VALUES(%s,%s,%s,%s,%s)",
                     (name, price, "[DUMMY] " + desc, tags + ["dummy"], random.choice(["ready", "ready", "terbatas", "pre-order"])))

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=23, minutes=50)
    rows = []

    def ev(platform, typ, ts, **payload):
        payload["dummy"] = True
        rows.append((platform, typ, json.dumps(payload), ts))

    users = [(f"{n}_{random.randint(10, 999)}", f"dummy-v{i}", pick(REGIONS)) for i, n in enumerate(NAMES * 6)]
    t = start
    while t < now:
        f = activity(t)
        for plat, _ in PLATFORMS:
            share = dict(PLATFORMS)[plat] / 100
            ev(plat, "viewer_count", t, viewer_count=int((120 + 2400 * f) * share * random.uniform(0.9, 1.1)))
        for _ in range(int(2 + 14 * f * random.uniform(0.7, 1.3))):
            ts = t + timedelta(seconds=random.randint(0, 899))
            plat = pick(PLATFORMS)
            nick, vid, reg = random.choice(users)
            p = random.choices(PRODUCTS, WEIGHTS)[0][0]
            tpl = random.choices([QUESTION, POSITIVE, NEUTRAL, NEGATIVE], [40, 25, 25, 10])[0]
            ev(plat, "comment", ts, comment=random.choice(tpl).format(p=p), nickname=nick, viewer_hash=vid, region=reg)
        for _ in range(int(1 + 4 * f)):
            nick, vid, reg = random.choice(users)
            ev(pick(PLATFORMS), "like", t + timedelta(seconds=random.randint(0, 899)),
               count=random.randint(10, 200), viewer_hash=vid, region=reg)
        for typ, rate in (("gift", 0.8), ("follow", 1.5), ("share", 0.6)):
            for _ in range(int(rate * f * 3 + random.random())):
                nick, vid, reg = random.choice(users)
                ev(pick(PLATFORMS), typ, t + timedelta(seconds=random.randint(0, 899)),
                   nickname=nick, viewer_hash=vid, region=reg)
        t += timedelta(minutes=15)

    with conn.cursor() as cur:
        cur.executemany("INSERT INTO events(platform,event_type,payload,created_at) VALUES(%s,%s,%s,%s)", rows)

    for i in range(30):
        name, price, desc, tags = random.choices(PRODUCTS, WEIGHTS)[0]
        budget = int(price * random.uniform(1.0, 1.5) / 10000) * 10000
        comment = random.choice([f"cari {tags[0]} {tags[1]} budget {budget}", f"{name} cocok buat kerja?",
                                 f"rekomendasi {tags[0]} di bawah {budget}"])
        rec = {"product": {"name": name, "price": price, "tags": tags}, "score": random.randint(2, 6),
               "reasons": ["Kata kunci kebutuhan cocok: " + tags[0], "Harga dibandingkan dengan budget yang disebutkan"],
               "caveat": "DUMMY data untuk demo dashboard.", "dummy": True}
        conn.execute("INSERT INTO research_interactions(platform,viewer_hash,comment,recommendation,transparency,created_at) "
                     "VALUES(%s,%s,%s,%s,%s,%s)",
                     (random.choice(["tiktok", "shopee", "manual"]), f"dummy-r{i}", json.dumps(comment), json.dumps(rec),
                      json.dumps({"dummy": True}), now - timedelta(minutes=random.randint(5, 1400))))
    def likert(latent):
        return [max(1, min(5, round(latent + random.gauss(0, 0.55)))) for _ in range(4)]

    for i in range(N_SURVEY):
        eligible = random.random() > 0.08
        ans = {"v": "KUESIONER-DRAFT-2-SEDERHANA", "eligible": eligible, "dummy": True, "stimulus_shown": True,
               "screen": {"age18": True, "watched3m": eligible, "seen_ai": random.choices(["ya", "tidak_yakin", "tidak"], [60, 30, 10])[0]},
               "X": None, "Y": None, "Z": None, "duration_s": random.randint(150, 600),
               "profile": {"age_range": random.choices(["18-24", "25-34", "35-44", "45+"], [40, 35, 18, 7])[0],
                           "platform": pick([("shopee", 45), ("tiktok", 40), ("instagram", 10), ("lainnya", 5)]),
                           "freq": random.choice(["jarang", "1-2/minggu", "3-5/minggu", "hampir_setiap_hari"])}}
        if eligible:
            # pola sintetis hanya untuk uji tampilan (BUKAN hasil penelitian)
            x, z = random.gauss(3.6, 0.7), random.gauss(3.3, 0.8)
            y = 1.3 + 0.45 * x + 0.12 * z + 0.15 * (x - 3.6) * (z - 3.3) + random.gauss(0, 0.45)
            ans.update(X=likert(x), Y=likert(y), Z=likert(z))
        conn.execute("INSERT INTO trust_surveys(respondent_code,answers,consent,created_at) VALUES(%s,%s,true,%s)",
                     (f"dummy-s{i}", json.dumps(ans), now - timedelta(hours=random.randint(1, 240))))
    return len(rows)


with psycopg.connect(DB) as conn:
    clean(conn)
    if "--clean" in sys.argv:
        print("Dummy data dihapus.")
    else:
        print(f"Seed selesai: {len(PRODUCTS)} produk, {seed(conn)} events, 30 interaksi, {N_SURVEY} kuesioner (semua bertanda dummy).")
