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

    # Categories table (allows adding/deleting dynamic custom categories)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)

    # Exclusion keywords table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS exclude_keywords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT UNIQUE NOT NULL
    )
    """)

    # Transactions table
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
        is_excluded INTEGER DEFAULT 0,
        UNIQUE(date, description, amount)
    )
    """)

    # Schema migration checks
    cursor.execute("PRAGMA table_info(transactions)")
    existing_columns = [col[1] for col in cursor.fetchall()]
    if "is_excluded" not in existing_columns and len(existing_columns) > 0:
        cursor.execute("ALTER TABLE transactions ADD COLUMN is_excluded INTEGER DEFAULT 0")

    if "category" not in existing_columns and len(existing_columns) > 0:
        cursor.execute("ALTER TABLE transactions ADD COLUMN category TEXT DEFAULT 'Uncategorized'")

    # Seed an initial default category if none exist
    cursor.execute("SELECT COUNT(*) FROM categories")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES ('Uncategorized')")

    conn.commit()
    conn.close()

def clear_all_transactions():
    """Wipes transactions table in SQLite."""
    conn = get_db_connection()
    conn.execute("DELETE FROM transactions")
    conn.commit()
    conn.close()

def calculate_cycle(date_str: str) -> str:
    """Converts transaction date into a billing cycle label (e.g. Sep 2026)."""
    try:
        dt = datetime.strptime(date_str, "%m/%d/%Y")
    except ValueError:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return "Unknown Cycle"

    if dt.day >= 25:
        if dt.month == 12:
            cycle_dt = datetime(dt.year + 1, 1, 1)
        else:
            cycle_dt = datetime(dt.year, dt.month + 1, 1)
    else:
        cycle_dt = datetime(dt.year, dt.month, 1)

    return cycle_dt.strftime("%b %Y")

def get_keywords():
    conn = get_db_connection()
    keywords = [row["keyword"] for row in conn.execute("SELECT keyword FROM exclude_keywords ORDER BY keyword ASC").fetchall()]
    conn.close()
    return keywords

def add_keyword(kw: str):
    if not kw.strip():
        return
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO exclude_keywords (keyword) VALUES (?)", (kw.strip().upper(),))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def delete_keyword(kw: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM exclude_keywords WHERE keyword = ?", (kw,))
    conn.commit()
    conn.close()

# Dynamic Category Functions
def get_categories():
    conn = get_db_connection()
    categories = [row["name"] for row in conn.execute("SELECT name FROM categories ORDER BY name ASC").fetchall()]
    conn.close()
    if not categories:
        return ["Uncategorized"]
    return categories

def add_category(cat_name: str):
    if not cat_name.strip():
        return
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO categories (name) VALUES (?)", (cat_name.strip(),))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def delete_category(cat_name: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM categories WHERE name = ?", (cat_name,))
    conn.commit()
    conn.close()

def is_auto_excluded(description: str, amount: float, active_keywords: list) -> bool:
    if amount > 0:
        return True
    desc_upper = description.upper()
    return any(kw in desc_upper for kw in active_keywords)

def update_transaction_status(tx_id: int, is_excluded: int, category: str):
    conn = get_db_connection()
    conn.execute("UPDATE transactions SET is_excluded = ?, category = ? WHERE id = ?", (is_excluded, category, tx_id))
    conn.commit()
    conn.close()

def find_column(df_cols, possible_names):
    cols_upper = {str(c).strip().upper(): c for c in df_cols}
    for name in possible_names:
        if name.upper() in cols_upper:
            return cols_upper[name.upper()]
    return None

st.set_page_config(page_title="Personal Spending Tracker", page_icon="💳", layout="wide")
init_db()

st.title("💳 Personal Spending Tracker")

active_keywords = get_keywords()
active_categories = get_categories()

# Sidebar: Management Tools
with st.sidebar:
    st.header("📂 CSV File Importer")
    uploaded_files = st.file_uploader("Upload Checking CSV Files", type=["csv"], accept_multiple_files=True)

    if uploaded_files:
        st.info("💡 **File uploaded!** Click the **'Review & Select Imports'** tab in the main window to choose rows.")

    st.divider()
    st.header("🏷️ Personal Categories Manager")
    st.caption("Build custom categories as you go.")
    new_cat = st.text_input("Add Custom Category")
    if st.button("Add Category") and new_cat:
        add_category(new_cat)
        st.success(f"Added category: '{new_cat.strip()}'")
        st.rerun()

    if active_categories:
        cat_to_delete = st.selectbox("Current Categories", active_categories)
        if st.button("Delete Selected Category") and cat_to_delete:
            delete_category(cat_to_delete)
            st.warning(f"Deleted category '{cat_to_delete}'")
            st.rerun()

    st.divider()
    st.header("🔍 Auto-Exclude Keywords")
    new_kw = st.text_input("Add Keyword (e.g., AMAZON)")
    if st.button("Add Keyword") and new_kw:
        add_keyword(new_kw)
        st.success(f"Added keyword: '{new_kw.upper()}'")
        st.rerun()

    selected_kw_to_delete = st.selectbox("Current Keywords", active_keywords)
    if st.button("Delete Selected Keyword") and selected_kw_to_delete:
        delete_keyword(selected_kw_to_delete)
        st.warning(f"Deleted '{selected_kw_to_delete}'")
        st.rerun()

    st.divider()
    st.header("⚠️ Database Tools")
    if st.button("Clear Database"):
        clear_all_transactions()
        st.warning("Database cleared.")
        st.rerun()

# Define Navigation Tabs
tab1, tab2, tab3 = st.tabs([
    "📊 Personal Budget Dashboard", 
    "📥 Review & Select Imports", 
    "⚙️ Tag & Categorize Transactions"
])

# Tab 2: Line-by-Line CSV Selection
with tab2:
    st.subheader("Line-by-Line CSV Row Selection")
    
    if not uploaded_files:
        st.info("Please upload a CSV file in the sidebar to review and select individual transaction rows.")
    else:
        all_staged_rows = []
        for file in uploaded_files:
            file.seek(0)
            df = pd.read_csv(file)
            
            date_col = find_column(df.columns, ["DATE", "POST DATE", "TRANSACTION DATE"])
            desc_col = find_column(df.columns, ["DESCRIPTION", "PAYEE", "NAME", "MEMO"])
            amount_col = find_column(df.columns, ["AMOUNT", "TRANS AMOUNT"])
            check_col = find_column(df.columns, ["CHECK #", "CHECK NUMBER", "CHECK"])
            status_col = find_column(df.columns, ["STATUS"])

            if not (date_col and desc_col and amount_col):
                st.error(f"File **{file.name}** is missing required Date, Description, or Amount columns.")
                continue

            for idx, row in df.iterrows():
                date_val = str(row[date_col]).strip() if pd.notna(row[date_col]) else ""
                desc_val = str(row[desc_col]).strip() if pd.notna(row[desc_col]) else ""
                
                try:
                    amount_val = float(row[amount_col])
                except (ValueError, TypeError):
                    continue

                check_val = str(row[check_col]) if check_col and pd.notna(row[check_col]) else ""
                status_val = str(row[status_col]) if status_col and pd.notna(row[status_col]) else ""
                cycle_val = calculate_cycle(date_val)
                auto_ex = is_auto_excluded(desc_val, amount_val, active_keywords)

                all_staged_rows.append({
                    "Import?": True,
                    "Date": date_val,
                    "Description": desc_val,
                    "Amount": amount_val,
                    "Cycle": cycle_val,
                    "Include in Personal Budget?": not auto_ex,
                    "Check #": check_val,
                    "Status": status_val,
                    "Source File": file.name
                })

        if all_staged_rows:
            staged_df = pd.DataFrame(all_staged_rows)

            st.write("Use the checkboxes in the **Import?** column to select or unselect individual lines:")

            edited_df = st.data_editor(
                staged_df,
                column_config={
                    "Import?": st.column_config.CheckboxColumn("Import?", default=True),
                    "Include in Personal Budget?": st.column_config.CheckboxColumn("Personal Budget?", default=True),
                    "Amount": st.column_config.NumberColumn("Amount ($)", format="$%.2f"),
                },
                disabled=["Date", "Description", "Amount", "Cycle", "Check #", "Status", "Source File"],
                use_container_width=True,
                key="csv_line_editor"
            )

            selected_rows = edited_df[edited_df["Import?"] == True]
            st.write(f"**Selected for import:** {len(selected_rows)} of {len(edited_df)} rows")

            if st.button("Import Selected Lines", type="primary"):
                conn = get_db_connection()
                imported_count = 0
                skipped_count = 0

                for _, row in selected_rows.iterrows():
                    is_excluded_val = 0 if row["Include in Personal Budget?"] else 1
                    try:
                        conn.execute(
                            """
                            INSERT INTO transactions (date, cycle_name, description, amount, check_num, status, category, is_excluded)
                            VALUES (?, ?, ?, ?, ?, ?, 'Uncategorized', ?)
                            """,
                            (row["Date"], row["Cycle"], row["Description"], float(row["Amount"]), row["Check #"], row["Status"], is_excluded_val),
                        )
                        imported_count += 1
                    except sqlite3.IntegrityError:
                        skipped_count += 1

                conn.commit()
                conn.close()
                st.success(f"Successfully imported {imported_count} row(s) into database! ({skipped_count} duplicates skipped).")
                st.rerun()

# Fetch transactions from SQLite DB
conn = get_db_connection()
df_tx = pd.read_sql_query("SELECT * FROM transactions", conn)
conn.close()

# Tab 1: Dashboard
with tab1:
    if df_tx.empty or "is_excluded" not in df_tx.columns:
        st.info("No transaction data loaded yet. Upload your bank CSV file and click the **Review & Select Imports** tab to choose transactions.")
    else:
        cycles = sorted(df_tx["cycle_name"].unique().tolist(), reverse=True)
        selected_cycle = st.selectbox("Select Billing Cycle to View", cycles)

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

# Tab 3: Categorize & Tag
with tab3:
    if df_tx.empty or "is_excluded" not in df_tx.columns:
        st.info("No transaction data loaded yet.")
    else:
        st.subheader("Tag & Categorize Personal Transactions")
        filter_cycle = st.selectbox("Filter Billing Cycle", cycles, key="tag_cycle_filter")
        cycle_all_df = df_tx[df_tx["cycle_name"] == filter_cycle]
        all_cats = get_categories()

        for _, row in cycle_all_df.iterrows():
            r1, r2, r3, r4, r5 = st.columns([1.5, 3.5, 1.5, 2.0, 2.0])
            r1.write(row["date"])
            r2.write(row["description"])
            r3.write(f"${row['amount']:,.2f}")

            is_personal = r4.checkbox("Include in Personal Budget", value=(row["is_excluded"] == 0), key=f"chk_{row['id']}")

            curr_idx = all_cats.index(row["category"]) if row["category"] in all_cats else 0
            selected_cat = r5.selectbox("Category", all_cats, index=curr_idx, key=f"cat_{row['id']}", label_visibility="collapsed")

            new_excluded_val = 0 if is_personal else 1
            if new_excluded_val != row["is_excluded"] or selected_cat != row["category"]:
                update_transaction_status(row["id"], new_excluded_val, selected_cat)
                st.rerun()