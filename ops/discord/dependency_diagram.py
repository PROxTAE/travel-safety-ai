#!/usr/bin/env python
"""Render the team dependency diagram (who waits for whom, who can work in
parallel) as docs/diagrams/team-dependency.png, Thai text, brand colours.

    python dependency_diagram.py            # write the PNG
    python dependency_diagram.py --post     # also post it to #project-summary (+ pin)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / "docs" / "diagrams" / "team-dependency.png"

NAVY, MINT, TEAL, ORANGE, CORAL, GREY = "#103653", "#25C7AE", "#0FA78F", "#FF8A1F", "#F05252", "#6B7A8A"
BG = "#F5FFFC"

# key -> (label, colour, x, y)  — grid units
NODES = {
    "01": ("01 Web\nหน้าเว็บ", "#25C7AE", 2.8, 3.0),
    "02": ("02 API\nประตูหน้าบ้าน", "#0FA78F", 2.8, 2.0),
    "03": ("03 Agent\nผู้ประสานงาน", "#4FB8D0", 2.8, 1.0),
    "04": ("04 External Data\nคนหาข้อมูล", "#7657D6", 0.0, 0.0),
    "05": ("05 Data Integration\nคนจัดระเบียบ", "#103653", 1.4, 0.0),
    "06": ("06 Risk & Knowledge\nคนประเมินความเสี่ยง", "#F05252", 2.8, 0.0),
    "07": ("07 Decision Engine\nคนตัดสินใจ", "#FF8A1F", 4.2, 0.0),
    "08": ("08 Recommendation\nคนส่งมอบ", "#10B981", 5.6, 0.0),
}
# (from, to, style)  solid = ต้องรอของจริง merge ก่อนต่อจริง, dashed = ทำด้วย fixture ไปก่อนได้
EDGES = [
    ("04", "05", "solid"), ("05", "06", "solid"), ("06", "07", "solid"), ("07", "08", "solid"),
    ("04", "03", "dashed"), ("05", "03", "dashed"), ("06", "03", "dashed"), ("07", "03", "dashed"), ("08", "03", "dashed"),
    ("03", "02", "solid"), ("02", "01", "solid"),
]


def thai_font() -> font_manager.FontProperties:
    for name in ("LeelawUI.ttf", "leelawad.ttf", "tahoma.ttf"):
        p = Path("C:/Windows/Fonts") / name
        if p.exists():
            return font_manager.FontProperties(fname=str(p))
    return font_manager.FontProperties()


def render(out: Path) -> Path:
    fp = thai_font()
    fpb = font_manager.FontProperties(fname=fp.get_file(), weight="bold") if fp.get_file() else fp
    fig, ax = plt.subplots(figsize=(16, 9), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(-2.9, 6.3)
    ax.set_ylim(-1.55, 4.35)
    ax.axis("off")

    # ---- title
    ax.text(1.7, 4.15, "ใครทำก่อน-หลัง / ใครรอใคร — SafetyTravel Assistant", fontproperties=fpb, fontsize=20, color=NAVY, ha="center")
    ax.text(1.7, 3.85, "ทุกคนเริ่มพร้อมกันตั้งแต่วันแรก · ลูกศรคือ \"ของจริง\" ที่ต้องไหลไปหากันตอนรวมระบบ",
            fontproperties=fp, fontsize=12.5, color=GREY, ha="center")

    # ---- left panel: start together
    panel = FancyBboxPatch((-2.8, -0.55), 1.75, 4.1, boxstyle="round,pad=0.02,rounding_size=0.08",
                           fc="#FFFFFF", ec=MINT, lw=2)
    ax.add_patch(panel)
    ax.text(-1.925, 3.3, "สัปดาห์แรก: ทุกคนทำพร้อมกัน", fontproperties=fpb, fontsize=13, color=TEAL, ha="center")
    lines = [
        "Phase 0  ตกลง \"แบบฟอร์มกลาง\"",
        "            (contract) กับเพื่อนข้าง ๆ",
        "Phase 1  โครง service ใน Docker",
        "            ขึ้น healthy ให้ได้",
        "",
        "ไม่มีใครต้องนั่งรอใคร",
        "ทำงานส่วนตัวเองด้วยข้อมูล",
        "ตัวอย่างจริง (fixture) ไปก่อน",
        "",
        "ที่ต้องเสร็จก่อนเพื่อน:",
        "02 API — contract กลาง",
        "(packages/contracts) merge",
        "เข้า main ให้เร็วที่สุด",
        "ทุกคนใช้ generate schema",
    ]
    y = 2.95
    for ln in lines:
        bold = ln.startswith(("02 API", "ที่ต้องเสร็จ", "ไม่มีใคร"))
        ax.text(-2.68, y, ln, fontproperties=fpb if bold else fp, fontsize=10.5,
                color=ORANGE if ln.startswith("02 API") else NAVY, ha="left", va="top")
        y -= 0.245

    # ---- edges (draw first so boxes cover the ends)
    HW, HH = 0.5, 0.27   # half box width/height
    for a, b, style in EDGES:
        _, _, xa, ya = NODES[a]
        _, _, xb, yb = NODES[b]
        dashed = style == "dashed"
        if ya == yb:                       # horizontal: edge to edge
            p0, p1, rad = (xa + HW, ya), (xb - HW, yb), 0.0
        elif xa == xb:                     # vertical
            p0, p1, rad = (xa, ya + HH), (xb, yb - HH), 0.0
        else:                              # diagonal: top edge of a -> bottom edge of b
            p0, p1, rad = (xa, ya + HH), (xb + (0.35 if xa > xb else -0.35), yb - HH), (-0.08 if xa < xb else 0.08)
        arr = FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=18,
                              lw=2.2 if not dashed else 1.4, color=NAVY if not dashed else GREY,
                              linestyle="-" if not dashed else (0, (5, 4)),
                              connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2, zorder=1)
        ax.add_patch(arr)

    # ---- nodes
    for key, (label, colour, x, y) in NODES.items():
        box = FancyBboxPatch((x - 0.5, y - 0.27), 1.0, 0.54, boxstyle="round,pad=0.02,rounding_size=0.06",
                             fc=colour, ec="white", lw=2, zorder=3)
        ax.add_patch(box)
        ax.text(x, y, label, fontproperties=fpb, fontsize=10.5 if y > 0 else 9.6, color="white", ha="center", va="center", zorder=4,
                linespacing=1.25)

    # ---- annotations
    ax.text(2.8, -0.62, "สายข้อมูล: 04 -> 05 -> 06 -> 07 -> 08  ทำไปพร้อมกันด้วย fixture ของคนก่อนหน้า  แล้ว \"ต่อของจริง\" ทีละคู่เมื่อคนก่อนหน้า merge",
            fontproperties=fp, fontsize=10.5, color=NAVY, ha="center")
    ax.text(3.55, 1.12, "03 เรียก 04–08 ผ่าน API ภายใน\nระหว่างรอใช้ stub จาก contract test",
            fontproperties=fp, fontsize=9.5, color=GREY, ha="left", va="center")
    ax.text(3.45, 2.5, "01 รอ public API ของ 02\nระหว่างรอทำหน้าจอ + สถานะ loading/degraded", fontproperties=fp, fontsize=9.5,
            color=GREY, ha="left", va="center")
    ax.text(3.45, 1.5, "02 รอผลจาก 03  ·  02 ทำ contract ให้ทุกคนก่อน", fontproperties=fp, fontsize=9.5, color=GREY, ha="left", va="center")

    # ---- legend
    lx, ly = -0.85, -1.05
    ax.add_patch(FancyArrowPatch((lx, ly), (lx + 0.5, ly), arrowstyle="-|>", mutation_scale=16, lw=2, color=NAVY))
    ax.text(lx + 0.6, ly, "ต้องรอของจริง merge ก่อนถึงต่อจริงได้ (ระหว่างนั้นใช้ fixture)", fontproperties=fp, fontsize=10, color=NAVY, va="center")
    ly2 = ly - 0.3
    ax.add_patch(FancyArrowPatch((lx, ly2), (lx + 0.5, ly2), arrowstyle="-|>", mutation_scale=16, lw=1.4, color=GREY, linestyle=(0, (5, 4))))
    ax.text(lx + 0.6, ly2, "เรียกผ่าน API ภายใน — ทำด้วย stub ไปก่อนได้ ต่อจริงตอนรวมระบบ", fontproperties=fp, fontsize=10, color=NAVY, va="center")
    ax.text(6.25, -1.45, "lead: Docker Compose รวมทุกกล่อง · รีวิว/merge · วันรวมระบบ (09_RUNBOOK)", fontproperties=fp, fontsize=9.5, color=GREY, ha="right")

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return out


def post(png: Path):
    from discord_api import Discord, load_dotenv
    load_dotenv()
    api = Discord()
    ids = json.loads((HERE / "out" / "discord-ids.json").read_text(encoding="utf-8"))
    ch, roles = ids["channel_ids"], ids["role_ids"]
    desc = (
        "**สรุปสั้น ๆ**\n"
        "• **ทุกคนเริ่มวันแรกพร้อมกัน** — Phase 0 (ตกลงแบบฟอร์มกลางกับเพื่อนข้าง ๆ) + Phase 1 (โครง service ใน Docker)\n"
        f"• <@&{roles['02-api']}> ต้อง merge **contract กลาง** เข้า main ก่อนใคร เพราะทุกคนใช้ generate schema\n"
        f"• สายข้อมูล <@&{roles['04-external-data']}> → <@&{roles['05-data-integration']}> → <@&{roles['06-risk-knowledge']}> → "
        f"<@&{roles['07-decision-engine']}> → <@&{roles['08-recommendation']}> ทำไปพร้อมกันด้วย **fixture** (ข้อมูลตัวอย่างจริงที่คนก่อนหน้าเก็บไว้) แล้วต่อของจริงทีละคู่เมื่อคนก่อนหน้า merge\n"
        f"• <@&{roles['03-agent']}> เรียก 04–08 ผ่าน API ภายใน ระหว่างรอใช้ stub จาก contract test\n"
        f"• <@&{roles['01-web']}> รอ public API ของ 02 ระหว่างรอทำหน้าจอทั้ง 7 หน้า + สถานะ loading / degraded\n\n"
        "**ใครรอใคร = รอแค่ตอน \"ต่อของจริง\"** ไม่ใช่รอเริ่มงาน · ติดคิวใคร คุยกันในห้องของคนนั้นหรือ <#" + ch["help"] + ">"
    )
    embed = {"title": "🔀 ใครทำก่อน-หลัง / ใครรอใคร", "description": desc, "color": 0x0FA78F,
             "image": {"url": f"attachment://{png.name}"},
             "footer": {"text": "SafetyTravel Assistant · ops/discord/dependency_diagram.py"}}
    msg = api.send_message(ch["project-summary"], {"content": "-# dependency-diagram", "embeds": [embed],
                                                   "allowed_mentions": {"parse": []}}, files=[(png.name, png)])
    api.pin_message(ch["project-summary"], msg["id"])
    print(f"posted + pinned in #project-summary: {msg['id']}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    png = render(Path(a.out))
    print(f"wrote {png}")
    if a.post:
        post(png)


if __name__ == "__main__":
    main()
