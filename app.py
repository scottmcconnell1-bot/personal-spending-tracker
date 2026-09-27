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
        category TEXT DEFAULT 'Uncategorized',
        UNIQUE(date, description, amount)
    )
    """)
    defaults = [
        "Personal Spending",
        "Groceries",
        "Utilities",
        "Housing",
        "Dining Out",
        "Entertainment",
        "Income",
        "Uncategorized",
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

def add_category(name: str) -> bool:
    if not name.strip():
        return False
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO categories (name) VALUES (?)", (name.strip(),))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def rename_category(old_name: str, new_name: str):
    if not new_name.strip():
        return
    conn = get_db_connection()
    conn.execute("UPDATE categories SET name = ? WHERE name = ?", (new_name.strip(), old_name))
    conn.execute("UPDATE transactions SET category = ? WHERE category = ?", (new_name.strip(), old_name))
    conn.commit()
    conn.close()

def delete_category(name: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM categories WHERE name = ?", (name,))
    conn.execute("UPDATE transactions SET category = 'Uncategorized' WHERE category = ?", (name,))
    conn.commit()
    conn.close()

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

            try:
                conn.execute(
                    """
                INSERT INTO transactions (date, cycle_name, description, amount, check_num, status, category)
                VALUES (?, ?, ?, ?, ?, ?, 'Uncategorized')
                """,
                    (date_val, cycle_val, desc_val, amount_val, check_val, status_val),
                )
                imported_count += 1
            except sqlite3.IntegrityError:
                skipped_count += 1

    conn.commit()
    conn.close()
    return imported_count, skipped_count

def update_transaction_category(tx_id: int, category: str):
    conn = get_db_connection()
    conn.execute("UPDATE transactions SET category = ? WHERE id = ?", (category, tx_id))
    conn.commit()
    conn.close()

st.set_page_config(page_title="Personal Spending Tracker", page_icon="💳", layout="wide")
init_db()

st.title("💳 Personal Spending Tracker & Budget Manager")

with st.sidebar:
    st.header("📂 CSV File Importer")
    uploaded_files = st.file_uploader("Upload Checking CSV Files", type=["csv"], accept_multiple_files=True)
    if uploaded_files and st.button("Import & Process Files"):
        added, skipped = import_csv_files(uploaded_files)
        st.success(f"Successfully imported **{added}** new records! ({skipped} duplicates automatically ignored).")
        st.rerun()

    st.divider()
    st.header("⚙️ Category Management")

    new_cat = st.text_input("Create Category")
    if st.button("Add Category") and new_cat:
        if add_category(new_cat):
            st.success(f"Added category: '{new_cat}'")
            st.rerun()
        else:
            st.error("Category already exists or is blank.")

    categories = get_categories()
    selected_cat_to_edit = st.selectbox("Select Category to Edit/Delete", categories)

    col_edit1, col_edit2 = st.columns(2)
    with col_edit1:
        rename_to = st.text_input("New Name", key="rename_input")
        if st.button("Rename") and rename_to:
            rename_category(selected_cat_to_edit, rename_to)
            st.success("Category renamed!")
            st.rerun()
    with col_edit2:
        if st.button("Delete"):
            if selected_cat_to_edit not in ["Personal Spending", "Uncategorized"]:
                delete_category(selected_cat_to_edit)
                st.warning(f"Deleted '{selected_cat_to_edit}'.")
                st.rerun()
            else:
                st.error("Cannot delete core system categories.")

tab1, tab2, tab3 = st.tabs(["📊 Dashboard & Budget", "🏷️ Tag Transactions", "📈 Monthly Comparisons"])

conn = get_db_connection()
df_tx = pd.read_sql_query("SELECT * FROM transactions", conn)
conn.close()

if df_tx.empty:
    st.info("No transaction data loaded yet. Please upload your bank CSV file using the sidebar to get started!")
else:
    cycles = sorted(df_tx["cycle_name"].unique().tolist(), reverse=True)

    with tab1:
        selected_cycle = st.selectbox("Select Billing Cycle", cycles)
        cycle_df = df_tx[df_tx["cycle_name"] == selected_cycle].copy()

        personal_df = cycle_df[(cycle_df["category"] == "Personal Spending") & (cycle_df["amount"] < 0)]
        total_personal_spent = abs(personal_df["amount"].sum())
        budget_limit = 750.00
        remaining_budget = budget_limit - total_personal_spent

        m1, m2, m3 = st.columns(3)
        m1.metric("Monthly Personal Budget", f"${budget_limit:,.2f}")
        m2.metric("Total Personal Spent", f"${total_personal_spent:,.2f}", delta=f"-${total_personal_spent:,.2f}")
        m3.metric("Budget Remaining", f"${remaining_budget:,.2f}", delta=f"${remaining_budget:,.2f}")

        st.progress(
            min(total_personal_spent / budget_limit, 1.0),
            text=f"Budget Usage: {(total_personal_spent / budget_limit) * 100:.1f}%",
        )

        st.divider()

        c1, c2 = st.columns(2)
        expenses_df = cycle_df[cycle_df["amount"] < 0].copy()
        expenses_df["abs_amount"] = expenses_df["amount"].abs()

        with c1:
            st.subheader("Expenses Distribution")
            if not expenses_df.empty:
                cat_summary = expenses_df.groupby("category")["abs_amount"].sum().reset_index()
                fig_pie = px.pie(cat_summary, values="abs_amount", names="category", hole=0.4, title=f"Category Breakdown ({selected_cycle})")
                st.plotly_chart(fig_pie, use_container_width=True)

        with c2:
            st.subheader("Top Expenses")
            if not expenses_df.empty:
                top_tx = expenses_df.sort_values(by="abs_amount", ascending=False).head(10)
                fig_bar = px.bar(top_tx, x="abs_amount", y="description", orientation="h", color="category", title="Top 10 Largest Expenses")
                st.plotly_chart(fig_bar, use_container_width=True)

    with tab2:
        st.subheader("Categorize Transactions")
        filter_cycle = st.selectbox("Filter Cycle", cycles, key="tag_cycle_filter")
        tag_df = df_tx[df_tx["cycle_name"] == filter_cycle]

        all_cats = get_categories()

        for _, row in tag_df.iterrows():
            r1, r2, r3, r4 = st.columns([1.5, 3.5, 1.5, 2.5])
            r1.write(row["date"])
            r2.write(row["description"])
            r3.write(f"${row['amount']:,.2f}")

            curr_idx = all_cats.index(row["category"]) if row["category"] in all_cats else 0
            selected_cat = r4.selectbox("Category", all_cats, index=curr_idx, key=f"tx_{row['id']}", label_visibility="collapsed")

            if selected_cat != row["category"]:
                update_transaction_category(row["id"], selected_cat)
                st.rerun()

    with tab3:
        st.subheader("Month-over-Month Spending Trends")
        all_exp = df_tx[df_tx["amount"] < 0].copy()
        all_exp["abs_amount"] = all_exp["amount"].abs()

        if not all_exp.empty:
            hist_summary = all_exp.groupby(["cycle_name", "category"])["abs_amount"].sum().reset_index()
            fig_hist = px.bar(hist_summary, x="cycle_name", y="abs_amount", color="category", barmode="group", title="Spending by Category Across All Cycles")
            st.plotly_chart(fig_hist, use_container_width=True)

            st.subheader("Personal Spending vs $750 Limit Over Time")
            p_trend = all_exp[all_exp["category"] == "Personal Spending"].groupby("cycle_name")["abs_amount"].sum().reset_index()
            if not p_trend.empty:
                fig_trend = px.line(p_trend, x="cycle_name", y="abs_amount", markers=True, title="Personal Spending Trend")
                fig_trend.add_hline(y=750, line_dash="dash", line_color="red", annotation_text="$750 Target Limit")
                st.plotly_chart(fig_trend, use_container_width=True)
