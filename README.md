# Live AI Dashboard — Live Commerce Intelligence

Dashboard analitik *live commerce* bertema ungu: penonton, engagement, komentar, produk paling dicari, sentimen, insight AI berbasis aturan, dan monitor riset (kuesioner X/Y/Z). Antarmuka dua bahasa (ID/EN).

*Purple-themed live commerce analytics dashboard: viewers, engagement, comments, top products, sentiment, rule-based AI insights, and a research monitor. Bilingual UI (ID/EN).*

## Fitur
- **Overview** — KPI + sparkline, kartu LIVE, grafik engagement & sentimen (tooltip), AI Copilot, peringkat produk, monitor riset.
- **Live Sessions** — tren 24 jam, komposisi platform, distribusi wilayah, feed komentar dengan filter.
- **Products** — katalog, pencarian, filter kategori, urutan (disebut/ditanya/sentimen/harga).
- **AI Insights** — rekomendasi otomatis, sentimen, keyword, FAQ berulang.
- **Research Lab** — rata-rata X/Y/Z, Cronbach α, regresi H1 & moderasi H2 (indikatif), export CSV.
- **Settings** — bahasa, auto refresh, halaman awal. Export JSON/CSV.

## Menjalankan
```bash
cp .env.example .env        # ganti POSTGRES_PASSWORD (dan di DATABASE_URL)
docker compose up -d --build
```
Buka `http://localhost:18090`.

Data demo (bertanda `dummy`, badge **DEMO DATA** muncul di dashboard):
```bash
docker compose exec -T dashboard python scripts/seed_dummy.py          # isi / isi ulang
docker compose exec -T dashboard python scripts/seed_dummy.py --clean  # hapus
```
Data event demo dibuat untuk 24 jam terakhir; jalankan ulang seed bila grafik kosong.

## Sumber data
Dashboard membaca tabel PostgreSQL di `db/schema.sql`: `events`, `product_catalog`, `research_interactions`, `trust_surveys`. Isi tabel dari connector/API milik Anda sendiri melalui jalur resmi platform.

## Keamanan
- Dashboard **belum memakai login**. Port hanya di-bind ke `127.0.0.1`. Jangan buka ke internet tanpa autentikasi (gunakan reverse proxy ber-auth, VPN, atau Tailscale).
- Jangan commit `.env`.
- Analitik sentimen/insight bersifat heuristik, bukan model AI tervalidasi.

## Struktur
```
dashboard/main.py     FastAPI + UI (HTML/JS tanpa library eksternal)
db/schema.sql         skema tabel
scripts/seed_dummy.py data demo
compose.yaml          dashboard + PostgreSQL
```
