"""Laporan harian live (WIB): rekap per slot jam ramai & per jam → xlsx / docx / pptx / pdf."""
import io, re
from collections import Counter
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))
SLOTS = [("Pagi", 9, 11), ("Siang (istirahat)", 11, 14), ("Sore", 16, 18), ("Malam", 19, 23)]
POS = ['bagus', 'suka', 'mantap', 'keren', 'menarik']
NEG = ['jelek', 'kecewa', 'mahal', 'buruk', 'tidak', 'nggak', 'gak']
INTENT = ['checkout', 'keep', 'beli', 'order', 'cari', 'harga', 'ready', 'stok', 'cod', 'promo']
QW = ['berapa', 'ada', 'stok', 'size', 'ukuran', 'harga', 'bisa', 'kapan', 'warna']


def slot_of(h):
    return next((n for n, a, b in SLOTS if a <= h < b), "Lainnya")


def build(db, day):
    """day: date (WIB). Mengembalikan dict rekap."""
    start = datetime(day.year, day.month, day.day, tzinfo=WIB)
    with db() as c:
        ev = c.execute("SELECT platform,event_type,payload,created_at FROM events WHERE created_at>=%s AND created_at<%s ORDER BY created_at",
                       (start, start + timedelta(days=1))).fetchall()
        prods = [r['name'] for r in c.execute('SELECT name FROM product_catalog').fetchall()]
    hours = {h: dict(komentar=0, likes=0, gift=0, follow=0, share=0, penonton=0, pos=0, neg=0, niat=0) for h in range(24)}
    vp = {}; pm = Counter(); qs = Counter(); plat = Counter()
    for e in ev:
        p = e['payload'] or {}; t = e['event_type'].lower(); h = e['created_at'].astimezone(WIB).hour; b = hours[h]; plat[e['platform']] += 1
        txt = str(p.get('comment') or p.get('message') or p.get('text') or '')
        if t in ('comment', 'chat', 'message') and txt:
            low = txt.lower(); b['komentar'] += 1
            if any(w in low for w in POS): b['pos'] += 1
            elif any(w in low for w in NEG): b['neg'] += 1
            if any(w in low for w in INTENT): b['niat'] += 1
            if '?' in txt or any(w in low for w in QW): qs[txt] += 1
            for n in prods:
                if n.lower() in low: pm[n] += 1
        elif t in ('viewer_count', 'roomuserseq', 'viewers'):
            k = (h, e['platform']); vp[k] = max(vp.get(k, 0), int(p.get('viewer_count') or p.get('count') or 0))
        elif 'like' in t: b['likes'] += int(p.get('count') or 1)
        elif 'gift' in t: b['gift'] += 1
        elif 'follow' in t: b['follow'] += 1
        elif 'share' in t: b['share'] += 1
    for (h, _), v in vp.items(): hours[h]['penonton'] += v

    def agg(hs):
        a = {k: sum(hours[h][k] for h in hs) for k in ('komentar', 'likes', 'gift', 'follow', 'share', 'pos', 'neg', 'niat')}
        a['penonton_puncak'] = max([hours[h]['penonton'] for h in hs] or [0])
        a['sentimen_positif'] = round(a['pos'] / (a['pos'] + a['neg']) * 100) if a['pos'] + a['neg'] else 0
        a['niat_beli'] = round(a['niat'] / a['komentar'] * 100, 1) if a['komentar'] else 0
        a['engagement'] = round((a['komentar'] + a['gift'] + a['share'] + a['follow']) / a['penonton_puncak'] * 100, 1) if a['penonton_puncak'] else 0
        return a
    slots = [{"slot": n, "jam": f"{a:02d}.00–{b:02d}.00", **agg(range(a, b))} for n, a, b in SLOTS]
    covered = {h for _, a, b in SLOTS for h in range(a, b)}
    slots.append({"slot": "Lainnya", "jam": "di luar slot", **agg([h for h in range(24) if h not in covered])})
    best = max(slots[:-1], key=lambda s: s['komentar']) if any(s['komentar'] for s in slots) else None
    return {"tanggal": day.strftime('%d-%m-%Y'), "dibuat": datetime.now(WIB).strftime('%d-%m-%Y %H:%M WIB'), "total": agg(range(24)),
            "slots": slots, "best": best, "jam": [{"jam": f"{h:02d}.00", "slot": slot_of(h), **hours[h]} for h in range(24)],
            "produk": pm.most_common(10), "pertanyaan": qs.most_common(10), "platform": dict(plat),
            "dummy": any((e['payload'] or {}).get('dummy') for e in ev)}


SLOT_COLS = [("Slot", "slot"), ("Jam (WIB)", "jam"), ("Komentar", "komentar"), ("Likes", "likes"), ("Gift", "gift"), ("Follow", "follow"),
             ("Penonton puncak", "penonton_puncak"), ("Sentimen + (%)", "sentimen_positif"), ("Niat beli (%)", "niat_beli"), ("Engagement (%)", "engagement")]
HOUR_COLS = [("Jam", "jam"), ("Slot", "slot"), ("Komentar", "komentar"), ("Likes", "likes"), ("Gift", "gift"), ("Penonton", "penonton")]
KPI = [("Komentar", "komentar"), ("Likes", "likes"), ("Gift", "gift"), ("Follow baru", "follow"), ("Share", "share"), ("Penonton puncak", "penonton_puncak"),
       ("Sentimen positif (%)", "sentimen_positif"), ("Niat beli (%)", "niat_beli"), ("Engagement (%)", "engagement")]


def _insight(r):
    out = []
    if r['best']: out.append(f"Slot paling ramai: {r['best']['slot']} ({r['best']['jam']} WIB) dengan {r['best']['komentar']} komentar.")
    if r['produk']: out.append(f"Produk paling disebut: {r['produk'][0][0]} ({r['produk'][0][1]}×).")
    if r['pertanyaan']: out.append(f"Pertanyaan terbanyak: \"{r['pertanyaan'][0][0][:80]}\".")
    if r['dummy']: out.append("Catatan: laporan berisi data DUMMY (uji tampilan).")
    return out or ["Belum ada data pada tanggal ini."]


def to_xlsx(r):
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Font, PatternFill
    wb = Workbook(); ws = wb.active; ws.title = "Ringkasan"
    hf, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1D4ED8")
    ws.append([f"Laporan Live Harian — {r['tanggal']}"]); ws['A1'].font = Font(bold=True, size=14); ws.append([f"Dibuat {r['dibuat']}"]); ws.append([])
    for k, v in KPI: ws.append([k, r['total'][v]])
    ws.append([]); [ws.append([s]) for s in _insight(r)]; ws.column_dimensions['A'].width = 28
    def sheet(name, cols, rows):
        w = wb.create_sheet(name); w.append([c for c, _ in cols])
        for c in w[1]: c.font, c.fill = hf, fill
        for row in rows: w.append([row[k] for _, k in cols])
        for i, (c, _) in enumerate(cols): w.column_dimensions[chr(65 + i)].width = max(12, len(c) + 3)
        return w
    ws2 = sheet("Per Slot", SLOT_COLS, r['slots'])
    ch = BarChart(); ch.title = "Komentar per slot"; ch.add_data(Reference(ws2, min_col=3, min_row=1, max_row=len(r['slots']) + 1), titles_from_data=True)
    ch.set_categories(Reference(ws2, min_col=1, min_row=2, max_row=len(r['slots']) + 1)); ws2.add_chart(ch, "L2")
    ws3 = sheet("Per Jam", HOUR_COLS, r['jam'])
    ch2 = BarChart(); ch2.title = "Komentar per jam"; ch2.add_data(Reference(ws3, min_col=3, min_row=1, max_row=25), titles_from_data=True)
    ch2.set_categories(Reference(ws3, min_col=1, min_row=2, max_row=25)); ch2.width = 22; ws3.add_chart(ch2, "H2")
    w = sheet("Produk & Pertanyaan", [("Produk", 0), ("Disebut", 1)], [{0: a, 1: b} for a, b in r['produk']])
    w.append([]); w.append(["Pertanyaan", "Jumlah"]); [w.append([a, b]) for a, b in r['pertanyaan']]; w.column_dimensions['A'].width = 60
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def to_docx(r):
    from docx import Document
    from docx.shared import Pt, RGBColor
    d = Document(); st = d.styles['Normal']; st.font.name = 'Calibri'; st.font.size = Pt(10)
    h = d.add_heading(f"Laporan Live Harian — {r['tanggal']}", 0); h.runs[0].font.color.rgb = RGBColor(0x1D, 0x4E, 0xD8)
    d.add_paragraph(f"Dibuat {r['dibuat']}")
    for s in _insight(r): d.add_paragraph(s, style='List Bullet')
    def tbl(cols, rows):
        t = d.add_table(rows=1, cols=len(cols)); t.style = 'Light Grid Accent 1'
        for i, (c, _) in enumerate(cols): t.rows[0].cells[i].text = c
        for row in rows:
            cells = t.add_row().cells
            for i, (_, k) in enumerate(cols): cells[i].text = str(row[k])
    d.add_heading("Ringkasan Hari Ini", 1); tbl([("Metrik", 0), ("Nilai", 1)], [{0: k, 1: r['total'][v]} for k, v in KPI])
    d.add_heading("Rekap per Slot Jam Ramai", 1); tbl(SLOT_COLS, r['slots'])
    d.add_heading("Rekap per Jam", 1); tbl(HOUR_COLS, r['jam'])
    d.add_heading("Produk Paling Disebut", 1); tbl([("Produk", 0), ("Disebut", 1)], [{0: a, 1: b} for a, b in r['produk']])
    d.add_heading("Pertanyaan Terbanyak", 1); tbl([("Pertanyaan", 0), ("Jumlah", 1)], [{0: a, 1: b} for a, b in r['pertanyaan']])
    buf = io.BytesIO(); d.save(buf); return buf.getvalue()


def to_pptx(r):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    pr = Presentation(); pr.slide_width, pr.slide_height = Inches(13.333), Inches(7.5); BLUE = RGBColor(0x1D, 0x4E, 0xD8)
    def slide(title):
        s = pr.slides.add_slide(pr.slide_layouts[5]); s.shapes.title.text = title
        s.shapes.title.text_frame.paragraphs[0].runs[0].font.color.rgb = BLUE; s.shapes.title.text_frame.paragraphs[0].runs[0].font.size = Pt(30); return s
    s = slide(f"Laporan Live Harian — {r['tanggal']}")
    tb = s.shapes.add_textbox(Inches(0.7), Inches(1.6), Inches(12), Inches(5)).text_frame
    for i, (k, v) in enumerate(KPI):
        p = tb.paragraphs[0] if i == 0 else tb.add_paragraph(); p.text = f"{k}: {r['total'][v]}"; p.font.size = Pt(20)
    for x in _insight(r):
        p = tb.add_paragraph(); p.text = "• " + x; p.font.size = Pt(18); p.font.bold = True
    s = slide("Komentar & Penonton per Slot Jam Ramai")
    cd = CategoryChartData(); cd.categories = [x['slot'] for x in r['slots']]; cd.add_series('Komentar', [x['komentar'] for x in r['slots']])
    s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.7), Inches(1.5), Inches(6), Inches(5.5), cd)
    cd2 = CategoryChartData(); cd2.categories = [x['slot'] for x in r['slots']]; cd2.add_series('Penonton puncak', [x['penonton_puncak'] for x in r['slots']])
    s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(6.9), Inches(1.5), Inches(6), Inches(5.5), cd2)
    s = slide("Komentar per Jam (WIB)")
    cd3 = CategoryChartData(); cd3.categories = [x['jam'] for x in r['jam']]; cd3.add_series('Komentar', [x['komentar'] for x in r['jam']])
    s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.7), Inches(1.5), Inches(12), Inches(5.5), cd3)
    s = slide("Tabel Rekap per Slot")
    t = s.shapes.add_table(len(r['slots']) + 1, len(SLOT_COLS), Inches(0.4), Inches(1.6), Inches(12.5), Inches(4)).table
    for i, (c, _) in enumerate(SLOT_COLS): t.cell(0, i).text = c
    for j, row in enumerate(r['slots'], 1):
        for i, (_, k) in enumerate(SLOT_COLS): t.cell(j, i).text = str(row[k])
    for row in t.rows:
        for c in row.cells:
            for p in c.text_frame.paragraphs: p.font.size = Pt(12)
    s = slide("Produk & Pertanyaan Teratas")
    tb = s.shapes.add_textbox(Inches(0.7), Inches(1.6), Inches(12), Inches(5.5)).text_frame; tb.word_wrap = True
    tb.paragraphs[0].text = "Produk paling disebut:"; tb.paragraphs[0].font.bold = True
    for a, b in r['produk'][:6]: p = tb.add_paragraph(); p.text = f"• {a} ({b}×)"; p.font.size = Pt(16)
    p = tb.add_paragraph(); p.text = "Pertanyaan terbanyak:"; p.font.bold = True
    for a, b in r['pertanyaan'][:6]: p = tb.add_paragraph(); p.text = f"• {a[:90]} ({b}×)"; p.font.size = Pt(16)
    buf = io.BytesIO(); pr.save(buf); return buf.getvalue()


def to_pdf(r):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from xml.sax.saxutils import escape
    buf = io.BytesIO(); ss = getSampleStyleSheet(); BLUE = colors.HexColor('#1D4ED8')
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=36, rightMargin=36, topMargin=30, bottomMargin=30, title=f"Laporan Live {r['tanggal']}")
    def tbl(cols, rows):
        t = Table([[c for c, _ in cols]] + [[str(x[k]) for _, k in cols] for x in rows], repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), BLUE), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('FONTSIZE', (0, 0), (-1, -1), 8),
                               ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EFF6FF')])]))
        return t
    el = [Paragraph(f"<font color='#1D4ED8'>Laporan Live Harian — {r['tanggal']}</font>", ss['Title']), Paragraph(f"Dibuat {r['dibuat']}", ss['Normal']), Spacer(1, 8)]
    el += [Paragraph("• " + escape(x), ss['Normal']) for x in _insight(r)] + [Spacer(1, 8)]
    el += [tbl([("Metrik", 0), ("Nilai", 1)], [{0: k, 1: r['total'][v]} for k, v in KPI]), Spacer(1, 10)]
    dr = Drawing(720, 180); bc = VerticalBarChart(); bc.x, bc.y, bc.width, bc.height = 40, 25, 660, 140
    bc.data = [[x['komentar'] for x in r['jam']]]; bc.categoryAxis.categoryNames = [x['jam'][:2] for x in r['jam']]; bc.bars[0].fillColor = BLUE
    bc.valueAxis.valueMin = 0; dr.add(bc)
    el += [Paragraph("Komentar per jam (WIB)", ss['Heading3']), dr, Paragraph("Rekap per slot jam ramai", ss['Heading3']), tbl(SLOT_COLS, r['slots']), Spacer(1, 10)]
    el += [Paragraph("Produk paling disebut", ss['Heading3']), tbl([("Produk", 0), ("Disebut", 1)], [{0: a, 1: b} for a, b in r['produk']]),
           Paragraph("Pertanyaan terbanyak", ss['Heading3']), tbl([("Pertanyaan", 0), ("Jumlah", 1)], [{0: escape(a[:110]), 1: b} for a, b in r['pertanyaan']])]
    doc.build(el); return buf.getvalue()


FMT = {"xlsx": (to_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
       "docx": (to_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
       "pptx": (to_pptx, "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
       "pdf": (to_pdf, "application/pdf")}
