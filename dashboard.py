
from pathlib import Path

import streamlit as st
import pandas as pd

CSV_FILE = Path(__file__).with_name("equipment_log.csv")

st.set_page_config(
    page_title="Internet Cafe Monitor",
    page_icon="🎮",
    layout="wide"
)

st.title("🎮 Internet Cafe Monitor")
st.caption("AI Equipment Monitoring Dashboard")

EQUIPMENT = [
    "Mouse",
    "Keyboard",
    "Headset",
    "Controller"
]


@st.fragment(run_every="5s")
def show_dashboard():

    if not CSV_FILE.exists():
        st.warning("ยังไม่พบไฟล์ equipment_log.csv")
        return

    try:
        df = pd.read_csv(
            CSV_FILE,
            encoding="utf-8-sig",
            dtype=str
        )
    except Exception:
        st.warning("กำลังรออ่านข้อมูล CSV")
        return

    if df.empty:
        st.warning("ยังไม่มีข้อมูล")
        return

    df.columns = df.columns.str.strip()

    if not all(name in df.columns for name in EQUIPMENT):
        st.error("หัวตาราง CSV ไม่ตรงกับที่กำหนด")
        st.write(df.columns.tolist())
        return

    latest = df.iloc[-1].copy()

    last_update = pd.to_datetime(
        str(latest.get("วันที่", "")) + " " +
        str(latest.get("เวลา", "")),
        format="%d/%m/%Y %H:%M:%S",
        errors="coerce"
    )

    if pd.isna(last_update):
        st.warning("ไม่สามารถตรวจสอบเวลาล่าสุดได้")
        latest[EQUIPMENT] = "ไม่ทราบ"

    else:
        age = (
            pd.Timestamp.now() - last_update
        ).total_seconds()

        st.caption(
            "อัปเดตล่าสุด: " +
            last_update.strftime("%d/%m/%Y %H:%M:%S")
        )

        if age > 65:
            st.error("ระบบ Offline หรือไม่มีข้อมูลใหม่")
            latest[EQUIPMENT] = "ไม่ทราบ"

    found = sum(
        str(latest[name]).strip() == "พบ"
        for name in EQUIPMENT
    )

    missing = [
        name for name in EQUIPMENT
        if str(latest[name]).strip() == "ไม่พบ"
    ]

    unknown = 4 - found - len(missing)

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("อุปกรณ์ทั้งหมด", 4)
    c2.metric("ตรวจพบ", found)
    c3.metric("ไม่พบ", len(missing))
    c4.metric("ไม่ทราบสถานะ", unknown)

    st.divider()
    st.subheader("สถานะอุปกรณ์ TABLE-01")

    if unknown:
        st.warning("ข้อมูลอุปกรณ์ไม่สมบูรณ์")
    elif not missing:
        st.success("อุปกรณ์ครบทั้งหมด")
    else:
        st.error(
            "อุปกรณ์ที่ไม่พบ: " + ", ".join(missing)
        )

    columns = st.columns(4)

    icons = ["🖱️", "⌨️", "🎧", "🎮"]

    for col, name, icon in zip(
        columns, EQUIPMENT, icons
    ):
        with col:
            st.subheader(icon + " " + name)

            status = str(latest[name]).strip()

            if status == "พบ":
                st.success("พบอุปกรณ์")
            elif status == "ไม่พบ":
                st.error("ไม่พบอุปกรณ์")
            else:
                st.warning("ไม่ทราบสถานะ")

    st.divider()
    st.subheader("กราฟจำนวนอุปกรณ์ที่ตรวจพบ")

    chart = df.tail(60).copy()

    chart["จำนวนอุปกรณ์"] = (
        chart[EQUIPMENT].eq("พบ").sum(axis=1)
    )

    valid = chart[EQUIPMENT].isin(
        ["พบ", "ไม่พบ"]
    ).all(axis=1)

    chart.loc[~valid, "จำนวนอุปกรณ์"] = float("nan")

    if "วันที่" in chart.columns and "เวลา" in chart.columns:
        chart["Timestamp"] = pd.to_datetime(
            chart["วันที่"] + " " + chart["เวลา"],
            dayfirst=True,
            errors="coerce"
        )

        chart = chart.dropna(subset=["Timestamp"])
        chart = chart.set_index("Timestamp")

    st.line_chart(chart["จำนวนอุปกรณ์"])

    st.divider()
    st.subheader("ประวัติการตรวจสอบ")

    st.dataframe(
        df.iloc[::-1].head(100),
        use_container_width=True,
        hide_index=True
    )

    st.download_button(
        label="ดาวน์โหลดประวัติ CSV",
        data=CSV_FILE.read_bytes(),
        file_name="equipment_log.csv",
        mime="text/csv"
    )

    st.caption("อ่านข้อมูลใหม่ทุก 5 วินาที")


show_dashboard()
