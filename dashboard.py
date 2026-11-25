
import streamlit as st
import pandas as pd
from supabase import create_client

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

TABLE_ID = "TABLE-01"
OFFLINE_AFTER = 65


@st.cache_resource
def connect_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SECRET_KEY"]
    )


@st.fragment(run_every="5s")
def show_dashboard():

    try:
        supabase = connect_supabase()

        response = (
            supabase.table("equipment_log")
            .select("*")
            .eq("table_id", TABLE_ID)
            .order("created_at", desc=True)
            .order("id", desc=True)
            .limit(100)
            .execute()
        )

        df = pd.DataFrame(response.data)

    except Exception as e:
        st.error("ไม่สามารถเชื่อมต่อ Supabase")
        st.caption(type(e).__name__)
        return

    if df.empty:
        st.warning("ยังไม่มีข้อมูลใน Supabase")
        return

    df = df.iloc[::-1].reset_index(drop=True)

    df["Timestamp"] = pd.to_datetime(
        df["created_at"],
        utc=True,
        errors="coerce",
        format="mixed"
    ).dt.tz_convert("Asia/Bangkok")

    df["วันที่"] = df["Timestamp"].dt.strftime(
        "%d/%m/%Y"
    )

    df["เวลา"] = df["Timestamp"].dt.strftime(
        "%H:%M:%S"
    )

    df = df.rename(columns={
        "table_id": "รหัสโต๊ะ",
        "mouse": "Mouse",
        "keyboard": "Keyboard",
        "headset": "Headset",
        "controller": "Controller",
        "found_count": "จำนวนที่พบ",
        "status": "สถานะ",
        "missing_items": "อุปกรณ์ที่ไม่พบ"
    })

    latest = df.iloc[-1].copy()

    last_update = latest["Timestamp"]

    if pd.isna(last_update):

        st.warning("ไม่สามารถตรวจสอบเวลาล่าสุด")
        latest[EQUIPMENT] = "ไม่ทราบ"

    else:

        age = (
            pd.Timestamp.now(tz="Asia/Bangkok")
            - last_update
        ).total_seconds()

        st.caption(
            "อัปเดตล่าสุด: " +
            last_update.strftime(
                "%d/%m/%Y %H:%M:%S"
            )
        )

        if age > OFFLINE_AFTER:

            st.error(
                "🔴 Offline - ไม่มีข้อมูลใหม่"
            )

            latest[EQUIPMENT] = "ไม่ทราบ"

        elif latest["สถานะ"] == "ไม่มีข้อมูลล่าสุด":

            st.warning(
                "🟡 เชื่อมต่อ Cloud ได้ แต่ไม่มีข้อมูล MQTT ล่าสุด"
            )

        else:

            st.success("🟢 System Online")

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

    st.subheader(
        "สถานะอุปกรณ์ " + TABLE_ID
    )

    if unknown:

        st.warning("ข้อมูลอุปกรณ์ไม่สมบูรณ์")

    elif not missing:

        st.success("อุปกรณ์ครบทั้งหมด")

    else:

        st.error(
            "อุปกรณ์ที่ไม่พบ: " +
            ", ".join(missing)
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

    st.subheader(
        "กราฟจำนวนอุปกรณ์ที่ตรวจพบ"
    )

    chart = df.tail(60).copy()

    chart["จำนวนอุปกรณ์"] = (
        chart[EQUIPMENT].eq("พบ").sum(axis=1)
    )

    valid = chart[EQUIPMENT].isin(
        ["พบ", "ไม่พบ"]
    ).all(axis=1)

    chart.loc[
        ~valid, "จำนวนอุปกรณ์"
    ] = float("nan")

    chart = chart.dropna(
        subset=["Timestamp"]
    )

    chart["Timestamp"] = (
        chart["Timestamp"].dt.tz_localize(None)
    )

    chart = chart.set_index("Timestamp")

    st.line_chart(chart["จำนวนอุปกรณ์"])

    st.divider()

    st.subheader("ประวัติการตรวจสอบ")

    history = df[[
        "วันที่",
        "เวลา",
        "รหัสโต๊ะ",
        "Mouse",
        "Keyboard",
        "Headset",
        "Controller",
        "จำนวนที่พบ",
        "สถานะ",
        "อุปกรณ์ที่ไม่พบ"
    ]].copy()

    history["จำนวนที่พบ"] = (
        history["จำนวนที่พบ"].astype("Int64")
    )

    st.dataframe(
        history.iloc[::-1],
        use_container_width=True,
        hide_index=True
    )

    csv_data = history.to_csv(
        index=False
    ).encode("utf-8-sig")

    st.download_button(
        label="ดาวน์โหลดประวัติ CSV",
        data=csv_data,
        file_name="equipment_log.csv",
        mime="text/csv"
    )

    st.caption(
        "Cloud Database: Supabase | "
        "อ่านข้อมูลใหม่ทุก 5 วินาที"
    )


show_dashboard()
