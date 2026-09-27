import os
import sqlite3
from datetime import datetime
import pandas as pd
import plotly.express as px
import streamlit as st

DB_FILE = "spending.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        cycle_name TEXT NOT NULL,
        description TEXT NOT NULL,
        amount REAL NOT NULL,
        check_num TEXT,
        status TEXT,
        category TEXT DEFAULT 'Personal Spending',
        is_excluded INTEGER DEFAULT 0,
        UNIQUE(date, description, amount)
    )
    """)
    
    defaults = [
        "Personal Spending",
        "Dining & Snacks",
        "Hobbies & Shopping",
        "Entertainment",
        "Miscellaneous Personal"
    ]
    for cat in defaults:
        cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))
    conn.commit()
    conn.close()

def calculate_cycle(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%m/%d/%Y")
    except ValueError:
        dt = datetime.strptime(date_str, "%Y-%m-%d")

    if dt.day >= 25:
        if dt.month == 12:
            cycle_dt = datetime(dt.year + 1, 1, 1)
        else:
            cycle_dt = datetime(dt.year, dt.month + 1, 1)
    else:
        cycle_dt = datetime(dt.year, dt.month, 1)

    return cycle_dt.strftime("%b %Y")

def get_categories():
    conn = get_db_connection()
    categories = [row["name"] for row in conn.execute("SELECT name FROM categories ORDER BY name ASC").fetchall()]
    conn.close()
    return categories

def is_auto_excluded(description: str, amount: float) -> bool:
    if amount > 0:
        return True
    
    desc_upper = description.upper()
    excluded_keywords = [
        "GROCERY", "WALMART", "KROGER", "ALDI", "SAFEWAY", "COSTCO",
        "SHELL", "CHEVRON", "EXXON", "MAVERIK", "FUEL", "GAS",
        "UTILITY", "POWER", "WATER", "MORTGAGE", "RENT", "INSURANCE"
    ]
    return any(keyword in desc_upper for keyword in excluded_keywords)

def import_csv_files(files):
    conn = get_db_connection()
    imported_count = 0
    skipped_count = 0

    for file in files:
        df = pd.read_csv(file)
        df.columns = [c.strip().upper() for c in df.columns]

        required = {"DATE", "DESCRIPTION", "AMOUNT"}
        if not required.issubset(set(df.columns)):
            st.error(f"File {file.name} is missing required columns.")
            continue

        for _, row in df.iterrows():
            date_val = str(row["DATE"]).strip()
            desc_val = str(row["DESCRIPTION"]).strip()
            amount_val = float(row["AMOUNT"])
            check_val = str(row["CHECK #"]) if "CHECK #" in df.columns and pd.notna(row["CHECK #"]) else ""
            status_val = str(row["STATUS"]) if "STATUS" in df.columns and pd.notna(row["STATUS"]) else ""
            cycle_val = calculate_cycle(date_val)
            excluded_flag = 1 if is_auto_excluded(desc_val, amount_val) else 0

            try:
                conn.execute(
                    """
                INSERT INTO transactions (date, cycle_name, description, amount, check_num, status, category, is_excluded)
                VALUES (?, ?, ?, ?, ?, ?, 'Personal Spending', ?)
                """,
                    (date_val, cycle_val, desc_val, amount_val, check_val, status_val, excluded_flag),
                )
                imported_count += 1
            except sqlite3.IntegrityError:
                skipped_count += 1

    conn.commit()
    conn.close()
    return imported_count, skipped_count

def update_transaction_status(tx_id: int, is_excluded: int, category: str):
    conn = get_db_connection()
    conn.execute("UPDATE transactions SET is_excluded = ?, category = ? WHERE id = ?", (is_excluded, category, tx_id))
    conn.commit()
    conn.close()

st.set_page_config(page_title="Personal Spending Tracker", page_icon="💳", layout="wide")
init_db()

st.title("💳 Personal Spending Tracker")

with st.sidebar:
    st.header("📂 CSV File Importer")
    uploaded_files = st.file_uploader("Upload Checking CSV Files", type=["csv"], accept_multiple_files=True)
    
    if uploaded_files:
        st.subheader("Select files to import:")
        file_dict = {f.name: f for f in uploaded_files}
        
        selected_filenames = [fname for fname in file_dict.keys() if st.checkbox(fname, value=True)]
        selected_files = [file_dict[fname] for fname in selected_filenames]
        
        if st.button("Import Selected Files"):
            if not selected_files:
                st.warning("No files selected for import.")
            else:
                added, skipped = import_csv_files(selected_files)
                st.success(f"Imported **{added}** records ({skipped} duplicates skipped). Auto-filtered non-personal items.")
                st.rerun()

tab1, tab2 = st.tabs(["📊 Personal Budget Dashboard", "⚙️ Filter & Tag Transactions"])

conn = get_db_connection()
df_tx = pd.read_sql_query("SELECT * FROM transactions", conn)
conn.close()

if df_tx.empty:
    st.info("No transaction data loaded yet. Upload your bank CSV file in the sidebar to get started!")
else:
    cycles = sorted(df_tx["cycle_name"].unique().tolist(), reverse=True)

    with tab1:
        selected_cycle = st.selectbox("Select Billing Cycle", cycles)
        
        personal_df = df_tx[(df_tx["cycle_name"] == selected_cycle) & (df_tx["is_excluded"] == 0) & (df_tx["amount"] < 0)].copy()
        
        total_personal_spent = abs(personal_df["amount"].sum())
        budget_limit = 750.00
        remaining_budget = budget_limit - total_personal_spent

        m1, m2, m3 = st.columns(3)
        m1.metric("Personal Budget Target", f"${budget_limit:,.2f}")
        m2.metric("Total Personal Spent", f"${total_personal_spent:,.2f}", delta=f"-${total_personal_spent:,.2f}")
        m3.metric("Budget Remaining", f"${remaining_budget:,.2f}", delta=f"${remaining_budget:,.2f}")

        st.progress(
            min(total_personal_spent / budget_limit, 1.0),
            text=f"Personal Budget Usage: {(total_personal_spent / budget_limit) * 100:.1f}%",
        )

        st.divider()

        if not personal_df.empty:
            personal_df["abs_amount"] = personal_df["amount"].abs()
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("Personal Spending Breakdown")
                cat_summary = personal_df.groupby("category")["abs_amount"].sum().reset_index()
                fig_pie = px.pie(cat_summary, values="abs_amount", names="category", hole=0.4)
                st.plotly_chart(fig_pie, use_container_width=True)

            with c2:
                st.subheader("Top Personal Purchases")
                top_tx = personal_df.sort_values(by="abs_amount", ascending=False).head(10)
                fig_bar = px.bar(top_tx, x="abs_amount", y="description", orientation="h", color="category")
                st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.success("No personal spending recorded for this cycle yet!")

    with tab2:
        st.subheader("Manage & Override Filtered Items")
        st.write("Toggle items off if they are bills/groceries/fuel, or re-include them if they are personal spending.")
        
        filter_cycle = st.selectbox("Filter Cycle", cycles, key="tag_cycle_filter")
        cycle_all_df = df_tx[df_tx["cycle_name"] == filter_cycle]
        all_cats = get_categories()

        for _, row in cycle_all_df.iterrows():
            r1, r2, r3, r4, r5 = st.columns([1.5, 3.5, 1.5, 2.0, 1.5])
            r1.write(row["date"])
            r2.write(row["description"])
            r3.write(f"${row['amount']:,.2f}")

            is_personal = r4.checkbox("Include in Personal", value=(row["is_excluded"] == 0), key=f"chk_{row['id']}")
            
            curr_idx = all_cats.index(row["category"]) if row["category"] in all_cats else 0
            selected_cat = r5.selectbox("Sub-Category", all_cats, index=curr_idx, key=f"cat_{row['id']}", label_visibility="collapsed")

            new_excluded_val = 0 if is_personal else 1
            if new_excluded_val != row["is_excluded"] or selected_cat != row["category"]:
                update_transaction_status(row["id"], new_excluded_val, selected_cat)
                st.rerun()
