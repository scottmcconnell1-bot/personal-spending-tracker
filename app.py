from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Personal Spending Tracker", page_icon="💳", layout="wide")

# ---------------------------------------------------------------------------
# Google Sheets storage (replaces SQLite so data survives app restarts)
# Your spreadsheet needs three tabs, each with this header row in row 1:
#   transactions: id | date | cycle_name | description | amount | check_num | status | category | is_excluded
#   categories:   name
#   keywords:     keyword
# ---------------------------------------------------------------------------
conn_gsheets = st.connection("gsheets", type=GSheetsConnection)

TX_COLS = ["id", "date", "cycle_name", "description", "amount", "check_num", "status", "category", "is_excluded"]
CAT_COLS = ["name"]
KW_COLS = ["keyword"]

READ_TTL = 30  # seconds; cache is also cleared after every write


def load_sheet(name: str, columns: list) -> pd.DataFrame:
    try:
        df = conn_gsheets.read(worksheet=name, ttl=READ_TTL)
    except Exception as e:
        st.error(
            f"Could not read the **{name}** tab of your Google Sheet. "
            f"Check that the tab exists, the header row is in place, and the sheet is shared with your service account.\n\n{e}"
        )
        st.stop()
    df = df.dropna(how="all")
    for c in columns:
        if c not in df.columns:
            df[c] = None
    return df[columns].copy()


def save_sheet(name: str, df: pd.DataFrame):
    conn_gsheets.update(worksheet=name, data=df)
    st.cache_data.clear()


def load_transactions() -> pd.DataFrame:
    df = load_sheet("transactions", TX_COLS)
    df["id"] = pd.to_numeric(df["id"], errors="coerce").fillna(0).astype(int)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["is_excluded"] = pd.to_numeric(df["is_excluded"], errors="coerce").fillna(0).astype(int)
    for c in ["date", "cycle_name", "description", "check_num", "status"]:
        df[c] = df[c].fillna("").astype(str)
    df["category"] = df["category"].fillna("Uncategorized").astype(str)
    return df


def clear_all_transactions():
    save_sheet("transactions", pd.DataFrame(columns=TX_COLS))


def calculate_cycle(date_str: str) -> str:
    """Converts transaction date into a billing cycle label (e.g. Sep 2026)."""
    dt = None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return "Unknown Cycle"

    if dt.day >= 25:
        if dt.month == 12:
            cycle_dt = datetime(dt.year + 1, 1, 1)
        else:
            cycle_dt = datetime(dt.year, dt.month + 1, 1)
    else:
        cycle_dt = datetime(dt.year, dt.month, 1)

    return cycle_dt.strftime("%b %Y")


# --- Keywords -------------------------------------------------------------
def get_keywords() -> list:
    df = load_sheet("keywords", KW_COLS)
    return sorted(df["keyword"].dropna().astype(str).tolist())


def add_keyword(kw: str):
    kw = kw.strip().upper()
    if not kw:
        return
    existing = get_keywords()
    if kw in existing:
        return
    save_sheet("keywords", pd.DataFrame({"keyword": existing + [kw]}))


def delete_keyword(kw: str):
    remaining = [k for k in get_keywords() if k != kw]
    save_sheet("keywords", pd.DataFrame({"keyword": remaining}, columns=KW_COLS))


# --- Categories -----------------------------------------------------------
def get_categories() -> list:
    df = load_sheet("categories", CAT_COLS)
    cats = sorted(df["name"].dropna().astype(str).tolist())
    return cats if cats else ["Uncategorized"]


def add_category(cat_name: str):
    cat_name = cat_name.strip()
    if not cat_name:
        return
    existing = get_categories()
    if cat_name in existing:
        return
    save_sheet("categories", pd.DataFrame({"name": existing + [cat_name]}))


def delete_category(cat_name: str):
    remaining = [c for c in get_categories() if c != cat_name]
    save_sheet("categories", pd.DataFrame({"name": remaining}, columns=CAT_COLS))


def is_auto_excluded(description: str, amount: float, active_keywords: list) -> bool:
    if amount > 0:
        return True
    desc_upper = description.upper()
    return any(kw in desc_upper for kw in active_keywords)


def find_column(df_cols, possible_names):
    cols_upper = {str(c).strip().upper(): c for c in df_cols}
    for name in possible_names:
        if name.upper() in cols_upper:
            return cols_upper[name.upper()]
    return None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
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
    confirm_clear = st.checkbox("I understand this deletes ALL saved transactions")
    if st.button("Clear Database") and confirm_clear:
        clear_all_transactions()
        st.warning("All transactions cleared.")
        st.rerun()

df_tx = load_transactions()

tab1, tab2, tab3 = st.tabs([
    "📊 Personal Budget Dashboard",
    "📥 Review & Select Imports",
    "⚙️ Tag & Categorize Transactions",
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
                    "Source File": file.name,
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
                key="csv_line_editor",
            )

            selected_rows = edited_df[edited_df["Import?"] == True]
            st.write(f"**Selected for import:** {len(selected_rows)} of {len(edited_df)} rows")

            if st.button("Import Selected Lines", type="primary"):
                existing_keys = set(zip(df_tx["date"], df_tx["description"], df_tx["amount"].round(2)))
                next_id = int(df_tx["id"].max()) + 1 if not df_tx.empty else 1
                new_rows = []
                skipped_count = 0

                for _, row in selected_rows.iterrows():
                    key = (row["Date"], row["Description"], round(float(row["Amount"]), 2))
                    if key in existing_keys:
                        skipped_count += 1
                        continue
                    existing_keys.add(key)
                    new_rows.append({
                        "id": next_id,
                        "date": row["Date"],
                        "cycle_name": row["Cycle"],
                        "description": row["Description"],
                        "amount": float(row["Amount"]),
                        "check_num": row["Check #"],
                        "status": row["Status"],
                        "category": "Uncategorized",
                        "is_excluded": 0 if row["Include in Personal Budget?"] else 1,
                    })
                    next_id += 1

                if new_rows:
                    combined = pd.concat([df_tx, pd.DataFrame(new_rows)], ignore_index=True)
                    save_sheet("transactions", combined[TX_COLS])
                st.success(f"Imported {len(new_rows)} row(s) to Google Sheets! ({skipped_count} duplicates skipped).")
                st.rerun()

# Tab 1: Dashboard
with tab1:
    if df_tx.empty:
        st.info("No transaction data loaded yet. Upload your bank CSV file and click the **Review & Select Imports** tab to choose transactions.")
    else:
        cycles = sorted(df_tx["cycle_name"].unique().tolist(), reverse=True)
        selected_cycle = st.selectbox("Select Billing Cycle to View", cycles)

        personal_df = df_tx[
            (df_tx["cycle_name"] == selected_cycle) & (df_tx["is_excluded"] == 0) & (df_tx["amount"] < 0)
        ].copy()

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

        # ---- Historical trend across ALL saved cycles ----
        st.divider()
        st.subheader("📈 Historical Spending (all cycles)")
        hist = df_tx[(df_tx["is_excluded"] == 0) & (df_tx["amount"] < 0)].copy()
        if not hist.empty:
            hist["abs_amount"] = hist["amount"].abs()
            hist["cycle_dt"] = pd.to_datetime(hist["cycle_name"], format="%b %Y", errors="coerce")
            hist = hist.dropna(subset=["cycle_dt"])

            by_cycle = hist.groupby(["cycle_dt", "category"])["abs_amount"].sum().reset_index()
            by_cycle["Cycle"] = by_cycle["cycle_dt"].dt.strftime("%b %Y")
            fig_hist = px.bar(by_cycle, x="Cycle", y="abs_amount", color="category",
                              labels={"abs_amount": "Spent ($)"})
            fig_hist.add_hline(y=budget_limit, line_dash="dash", annotation_text="Budget")
            st.plotly_chart(fig_hist, use_container_width=True)

            report = (
                hist.groupby("cycle_dt")["abs_amount"].sum().reset_index()
                .sort_values("cycle_dt", ascending=False)
            )
            report["Cycle"] = report["cycle_dt"].dt.strftime("%b %Y")
            report["Budget"] = budget_limit
            report["Under / (Over)"] = report["Budget"] - report["abs_amount"]
            report = report.rename(columns={"abs_amount": "Spent"})[["Cycle", "Spent", "Budget", "Under / (Over)"]]
            st.dataframe(report, hide_index=True, use_container_width=True)
            st.download_button("Download report (CSV)", report.to_csv(index=False), "spending_report.csv")
        else:
            st.info("No personal spending history yet.")

# Tab 3: Categorize & Tag
with tab3:
    if df_tx.empty:
        st.info("No transaction data loaded yet.")
    else:
        st.subheader("Tag & Categorize Personal Transactions")
        cycles_t3 = sorted(df_tx["cycle_name"].unique().tolist(), reverse=True)
        filter_cycle = st.selectbox("Filter Billing Cycle", cycles_t3, key="tag_cycle_filter")
        all_cats = get_categories()

        cycle_df = df_tx[df_tx["cycle_name"] == filter_cycle].copy()
        cycle_df["Include in Personal Budget?"] = cycle_df["is_excluded"] == 0
        # Make sure any existing category is a valid option in the dropdown
        options = sorted(set(all_cats) | set(cycle_df["category"].unique()))

        editor_df = cycle_df[["id", "date", "description", "amount", "Include in Personal Budget?", "category"]]

        edited_tags = st.data_editor(
            editor_df,
            column_config={
                "id": None,  # hidden
                "date": "Date",
                "description": "Description",
                "amount": st.column_config.NumberColumn("Amount ($)", format="$%.2f"),
                "Include in Personal Budget?": st.column_config.CheckboxColumn("Personal Budget?"),
                "category": st.column_config.SelectboxColumn("Category", options=options, required=True),
            },
            disabled=["id", "date", "description", "amount"],
            hide_index=True,
            use_container_width=True,
            key=f"tag_editor_{filter_cycle}",
        )

        if st.button("💾 Save Changes", type="primary"):
            updates = edited_tags.set_index("id")
            full = df_tx.set_index("id")
            full.loc[updates.index, "category"] = updates["category"]
            full.loc[updates.index, "is_excluded"] = (~updates["Include in Personal Budget?"]).astype(int)
            save_sheet("transactions", full.reset_index()[TX_COLS])
            st.success("Changes saved to Google Sheets.")
            st.rerun()