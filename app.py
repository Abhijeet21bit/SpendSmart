import sqlite3
from datetime import date
import pandas as pd
import plotly.express as px
import streamlit as st

DB_NAME = "expenses.db"
CATEGORIES = ["Food", "Travel", "Education", "Shopping", "Entertainment", "Bills", "Other"]
DEFAULT_BUDGET = 3000.0

st.set_page_config(page_title="SpendSmart", page_icon="💰", layout="wide")


def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def initialize_database():
    with get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL CHECK(amount > 0),
            category TEXT NOT NULL,
            description TEXT,
            expense_date TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS budgets (
            month TEXT PRIMARY KEY,
            amount REAL NOT NULL CHECK(amount >= 0)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS category_budgets (
            month TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount >= 0),
            PRIMARY KEY (month, category)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS recurring_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL CHECK(amount > 0),
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            day_of_month INTEGER NOT NULL CHECK(day_of_month BETWEEN 1 AND 31),
            active INTEGER NOT NULL DEFAULT 1,
            last_created_month TEXT
        )""")


def add_expense(amount, category, description, expense_date):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO expenses (amount, category, description, expense_date) VALUES (?, ?, ?, ?)",
            (float(amount), category, description.strip(), expense_date.isoformat()),
        )


def delete_expenses(expense_ids):
    ids = [int(x) for x in expense_ids]
    if ids:
        with get_connection() as conn:
            conn.executemany("DELETE FROM expenses WHERE id = ?", [(x,) for x in ids])


def load_expenses():
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT id, amount, category, description, expense_date FROM expenses ORDER BY expense_date DESC, id DESC",
            conn,
        )


def get_budget(month):
    with get_connection() as conn:
        row = conn.execute("SELECT amount FROM budgets WHERE month = ?", (month,)).fetchone()
    return float(row[0]) if row else DEFAULT_BUDGET


def save_budget(month, amount):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO budgets (month, amount) VALUES (?, ?) "
            "ON CONFLICT(month) DO UPDATE SET amount = excluded.amount",
            (month, float(amount)),
        )


def get_category_budgets(month):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT category, amount FROM category_budgets WHERE month = ?", (month,)
        ).fetchall()
    return {category: float(amount) for category, amount in rows}


def save_category_budget(month, category, amount):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO category_budgets (month, category, amount) VALUES (?, ?, ?) "
            "ON CONFLICT(month, category) DO UPDATE SET amount = excluded.amount",
            (month, category, float(amount)),
        )


def load_recurring():
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT id, amount, category, description, day_of_month, active, last_created_month "
            "FROM recurring_expenses ORDER BY id DESC", conn
        )


def add_recurring(amount, category, description, day_of_month):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO recurring_expenses (amount, category, description, day_of_month) VALUES (?, ?, ?, ?)",
            (float(amount), category, description.strip(), int(day_of_month)),
        )


def create_due_recurring(month):
    """Create each active recurring item at most once per selected month."""
    created = 0
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, amount, category, description, day_of_month FROM recurring_expenses "
            "WHERE active = 1 AND (last_created_month IS NULL OR last_created_month != ?)",
            (month,),
        ).fetchall()
        year, mon = map(int, month.split("-"))
        import calendar
        max_day = calendar.monthrange(year, mon)[1]
        for recurring_id, amount, category, description, day_num in rows:
            expense_day = date(year, mon, min(int(day_num), max_day))
            conn.execute(
                "INSERT INTO expenses (amount, category, description, expense_date) VALUES (?, ?, ?, ?)",
                (amount, category, description + " (recurring)", expense_day.isoformat()),
            )
            conn.execute(
                "UPDATE recurring_expenses SET last_created_month = ? WHERE id = ?",
                (month, recurring_id),
            )
            created += 1
    return created


def previous_month(month):
    year, mon = map(int, month.split("-"))
    return f"{year - 1:04d}-12" if mon == 1 else f"{year:04d}-{mon - 1:02d}"


def month_total(expenses, month):
    if expenses.empty:
        return 0.0
    dates = pd.to_datetime(expenses["expense_date"])
    return float(expenses.loc[dates.dt.strftime("%Y-%m") == month, "amount"].sum())


def money(value):
    return f"₹{value:,.2f}"


initialize_database()
st.title("SpendSmart")
st.caption("Personal Expense Management System | Track spending, budgets, and monthly trends")

with st.sidebar:
    st.header("Add an expense")
    with st.form("expense_form", clear_on_submit=True):
        amount = st.number_input("Amount (₹)", min_value=0.0, value=0.0, step=10.0, format="%.2f")
        category = st.selectbox("Category", CATEGORIES)
        description = st.text_input("Description", placeholder="e.g. lunch at college")
        expense_date = st.date_input("Date", value=date.today(), max_value=date.today())
        submitted = st.form_submit_button("Save expense", use_container_width=True)
        if submitted:
            if amount <= 0:
                st.error("Enter an amount greater than zero.")
            else:
                add_expense(amount, category, description, expense_date)
                st.success("Expense saved.")
                st.rerun()

    st.divider()
    st.header("Monthly budget")
    selected_month_date = st.date_input("Choose month", value=date.today(), key="budget_month")
    selected_month = selected_month_date.strftime("%Y-%m")
    current_budget = get_budget(selected_month)
    new_budget = st.number_input("Overall budget (₹)", min_value=0.0, value=float(current_budget), step=100.0)
    if st.button("Save overall budget", use_container_width=True):
        save_budget(selected_month, new_budget)
        st.success("Overall budget updated.")
        st.rerun()

all_expenses = load_expenses()
if not all_expenses.empty:
    all_expenses["expense_date"] = pd.to_datetime(all_expenses["expense_date"])
    month_expenses = all_expenses[all_expenses["expense_date"].dt.strftime("%Y-%m") == selected_month].copy()
else:
    month_expenses = pd.DataFrame(columns=["id", "amount", "category", "description", "expense_date"])

budget = get_budget(selected_month)
total = float(month_expenses["amount"].sum()) if not month_expenses.empty else 0.0
remaining = budget - total
spent_pct = (total / budget * 100) if budget > 0 else 0.0

c1, c2, c3 = st.columns(3)
c1.metric("Spent this month", money(total))
c2.metric("Monthly budget", money(budget))
c3.metric("Budget remaining", money(remaining), delta=f"{spent_pct:.1f}% used")
if budget > 0:
    st.progress(min(max(spent_pct / 100, 0.0), 1.0))
if remaining < 0:
    st.warning(f"You are {money(abs(remaining))} over your overall budget.")
elif budget > 0 and spent_pct >= 80:
    st.warning("You have used at least 80% of this month's overall budget.")

# Category-share warnings (no separate category budgets)
st.subheader("Category-wise spending alerts")
if not month_expenses.empty and total > 0:
    category_totals_for_alerts = month_expenses.groupby("category")["amount"].sum().sort_values(ascending=False)
    for cat, amount in category_totals_for_alerts.items():
        share = float(amount) / total * 100
        if share > 40:
            st.warning(
                f"{cat} accounts for {share:.1f}% of your spending this month "
                f"({money(float(amount))}). It is above the 40% concentration threshold."
            )
        elif share >= 30:
            st.info(f"{cat} accounts for {share:.1f}% of your spending this month. Keep an eye on it.")
else:
    st.info("Add expenses to see category-wise spending alerts. Alerts are based on the share of total spending, not separate category budgets.")

st.subheader("Spending overview")
left, right = st.columns(2)
with left:
    if not month_expenses.empty:
        category_totals = month_expenses.groupby("category", as_index=False)["amount"].sum()
        fig = px.pie(category_totals, names="category", values="amount", title="Spending by category")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No expenses recorded for this month yet. Add one from the sidebar.")
with right:
    if not month_expenses.empty:
        daily = month_expenses.groupby(month_expenses["expense_date"].dt.date, as_index=False)["amount"].sum()
        daily.columns = ["Date", "Amount"]
        fig = px.bar(daily, x="Date", y="Amount", title="Daily spending")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Your daily spending chart will appear here.")

# Smart insights (rule-based; no external AI/API required)
st.subheader("Smart spending insights")
insights = []
if month_expenses.empty:
    insights.append("Add a few expenses to receive spending insights for this month.")
else:
    category_totals = month_expenses.groupby("category")["amount"].sum().sort_values(ascending=False)
    top_cat = category_totals.index[0]
    share = category_totals.iloc[0] / total * 100 if total else 0
    insights.append(f"Your highest-spending category is **{top_cat}** at {money(category_totals.iloc[0])} ({share:.1f}% of this month's spending).")
    if budget > 0:
        if total > budget:
            insights.append(f"You have exceeded your overall budget by **{money(total - budget)}**. Consider reducing non-essential purchases.")
        elif spent_pct >= 80:
            insights.append(f"You have used **{spent_pct:.1f}%** of your overall budget. Only {money(remaining)} remains.")
        else:
            insights.append(f"You have used **{spent_pct:.1f}%** of your overall budget, so {money(remaining)} remains.")
    prev_month = previous_month(selected_month)
    prev_total = month_total(all_expenses, prev_month)
    if prev_total > 0:
        change = (total - prev_total) / prev_total * 100
        if change > 0:
            insights.append(f"Spending is **{change:.1f}% higher** than {prev_month} ({money(prev_total)} last month).")
        elif change < 0:
            insights.append(f"Spending is **{abs(change):.1f}% lower** than {prev_month} ({money(prev_total)} last month).")
        else:
            insights.append(f"Your spending is unchanged from {prev_month}.")
    for cat, cat_amount in category_totals.items():
        cat_share = float(cat_amount) / total * 100 if total else 0
        if cat_share > 40:
            insights.append(f"**{cat}** makes up {cat_share:.1f}% of your total spending, above the 40% alert threshold.")
for insight in insights:
    st.markdown(f"- {insight}")

# On-screen monthly report with optional CSV export
st.subheader(f"Monthly report — {selected_month}")
report_expenses = month_expenses.copy()
report_category = (
    report_expenses.groupby("category", as_index=False)["amount"].sum()
    .rename(columns={"category": "Category", "amount": "Spent (₹)"})
    if not report_expenses.empty else pd.DataFrame(columns=["Category", "Spent (₹)"])
)
report_summary = pd.DataFrame([{
    "Month": selected_month,
    "Overall budget (₹)": budget,
    "Total spent (₹)": total,
    "Budget remaining (₹)": remaining,
    "Number of expenses": int(len(report_expenses)),
}])
st.dataframe(report_summary, use_container_width=True, hide_index=True)
st.write("**Category breakdown**")
if report_category.empty:
    st.info("No category totals for this month yet.")
else:
    st.dataframe(report_category.sort_values("Spent (₹)", ascending=False), use_container_width=True, hide_index=True)
st.write("**Expense details**")
if report_expenses.empty:
    st.info("No expenses recorded for this month.")
else:
    details = report_expenses.assign(
        expense_date=report_expenses["expense_date"].dt.strftime("%Y-%m-%d")
    ).drop(columns=["id"], errors="ignore").rename(columns={
        "amount": "Amount (₹)", "category": "Category",
        "description": "Description", "expense_date": "Date"
    })
    st.dataframe(details, use_container_width=True, hide_index=True)

csv_report = (
    "MONTH SUMMARY\\n" + report_summary.to_csv(index=False)
    + "\\nCATEGORY BREAKDOWN\\n" + report_category.to_csv(index=False)
    + "\\nEXPENSE DETAILS\\n" + (
        report_expenses.assign(expense_date=report_expenses["expense_date"].dt.strftime("%Y-%m-%d"))
        .drop(columns=["id"], errors="ignore").rename(columns={
            "amount": "Amount (₹)", "category": "Category",
            "description": "Description", "expense_date": "Date"
        }).to_csv(index=False)
    )
).encode("utf-8")
st.download_button(
    "Export this monthly report as CSV (optional)",
    data=csv_report,
    file_name=f"spendsmart_monthly_report_{selected_month}.csv",
    mime="text/csv",
)

# Compare two distinct months
st.subheader("Compare two months")
available_months = sorted(
    all_expenses["expense_date"].dt.strftime("%Y-%m").unique().tolist()
) if not all_expenses.empty else []
today_month = date.today().strftime("%Y-%m")
if today_month not in available_months:
    available_months.append(today_month)
available_months = sorted(set(available_months))
cmp1, cmp2 = st.columns(2)
with cmp1:
    comparison_month_1 = st.selectbox(
        "First month", available_months,
        index=max(0, available_months.index(available_months[-2] if len(available_months) > 1 else available_months[-1])),
        key="comparison_month_1",
    )
with cmp2:
    default_second = available_months[-1]
    comparison_month_2 = st.selectbox(
        "Second month", available_months, index=available_months.index(default_second),
        key="comparison_month_2",
    )
if comparison_month_1 == comparison_month_2:
    st.info("Choose two different months to compare their spending.")
else:
    compare_df = all_expenses.copy()
    if not compare_df.empty:
        compare_df["Month"] = compare_df["expense_date"].dt.strftime("%Y-%m")
        compare_df = compare_df[compare_df["Month"].isin([comparison_month_1, comparison_month_2])]
        if compare_df.empty:
            st.info("No expenses found for these months.")
        else:
            monthly_category = (
                compare_df.groupby(["category", "Month"], as_index=False)["amount"].sum()
                .rename(columns={"category": "Category", "amount": "Amount (₹)"})
            )
            # Include zero-value categories so both months are clearly represented.
            all_cats = pd.DataFrame({"Category": CATEGORIES})
            months_frame = pd.DataFrame({"Month": [comparison_month_1, comparison_month_2]})
            full_index = all_cats.merge(months_frame, how="cross")
            monthly_category = full_index.merge(
                monthly_category, on=["Category", "Month"], how="left"
            ).fillna({"Amount (₹)": 0})
            fig_compare = px.bar(
                monthly_category, x="Category", y="Amount (₹)", color="Month",
                barmode="group",
                title=f"Category spending: {comparison_month_1} vs {comparison_month_2}",
                category_orders={"Month": [comparison_month_1, comparison_month_2]},
            )
            st.plotly_chart(fig_compare, use_container_width=True)
            monthly_totals_compare = (
                compare_df.groupby("Month", as_index=False)["amount"].sum()
                .rename(columns={"Month": "Month", "amount": "Total spent (₹)"})
            )
            st.write("**Total spending by month**")
            st.dataframe(monthly_totals_compare, use_container_width=True, hide_index=True)
    else:
        st.info("Add expenses in at least two different months to compare them.")

# Recurring expenses
st.subheader("Recurring expenses")
st.write("Save regular costs such as subscriptions, rent, or a monthly phone bill. They are added only when you press the button below.")
with st.form("recurring_form", clear_on_submit=True):
    r1, r2 = st.columns(2)
    with r1:
        recurring_amount = st.number_input("Recurring amount (₹)", min_value=0.0, value=0.0, step=10.0, key="recurring_amount")
        recurring_category = st.selectbox("Recurring category", CATEGORIES, key="recurring_category")
    with r2:
        recurring_description = st.text_input("Name / description", placeholder="e.g. music subscription", key="recurring_description")
        recurring_day = st.number_input("Day of month", min_value=1, max_value=31, value=1, step=1)
    recurring_submitted = st.form_submit_button("Save recurring expense")
    if recurring_submitted:
        if recurring_amount <= 0 or not recurring_description.strip():
            st.error("Enter an amount greater than zero and a description.")
        else:
            add_recurring(recurring_amount, recurring_category, recurring_description, recurring_day)
            st.success("Recurring expense saved.")
            st.rerun()

recurring_df = load_recurring()
if not recurring_df.empty:
    recurring_display = recurring_df.rename(columns={"id": "ID", "amount": "Amount (₹)", "category": "Category",
        "description": "Description", "day_of_month": "Day", "active": "Active", "last_created_month": "Last added month"})
    st.dataframe(recurring_display.drop(columns=["Last added month"], errors="ignore"), use_container_width=True, hide_index=True)
    if st.button(f"Add due recurring expenses to {selected_month}", type="secondary"):
        count = create_due_recurring(selected_month)
        st.success(f"Added {count} recurring expense(s) to {selected_month}. Items are not duplicated if you press the button again for the same month.")
        st.rerun()
    active_ids = recurring_df.loc[recurring_df["active"] == 1, "id"].astype(int).tolist()
    if active_ids:
        disable_id = st.selectbox("Pause a recurring expense", active_ids, format_func=lambda x: f"ID {x}: {recurring_df.loc[recurring_df['id'] == x, 'description'].iloc[0]}")
        if st.button("Pause selected recurring expense"):
            with get_connection() as conn:
                conn.execute("UPDATE recurring_expenses SET active = 0 WHERE id = ?", (int(disable_id),))
            st.success("Recurring expense paused.")
            st.rerun()

    recurring_ids = recurring_df["id"].astype(int).tolist()
    delete_recurring_id = st.selectbox(
        "Delete a recurring expense",
        recurring_ids,
        format_func=lambda x: f"ID {x}: {recurring_df.loc[recurring_df['id'] == x, 'description'].iloc[0]} (₹{recurring_df.loc[recurring_df['id'] == x, 'amount'].iloc[0]:,.2f})",
        key="delete_recurring_id",
    )
    confirm_delete_recurring = st.checkbox(
        "I understand this deletes the recurring rule, but keeps any expenses already added to my history.",
        key="confirm_delete_recurring",
    )
    if st.button("Delete selected recurring expense", type="secondary", disabled=not confirm_delete_recurring):
        with get_connection() as conn:
            conn.execute("DELETE FROM recurring_expenses WHERE id = ?", (int(delete_recurring_id),))
        st.success("Recurring expense deleted. Previously added expenses remain in your expense history.")
        st.rerun()
else:
    st.info("No recurring expenses set up yet.")

# Expense history and bulk deletion
st.subheader("Expense history")
if not all_expenses.empty:
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        category_filter = st.selectbox("Filter by category", ["All"] + CATEGORIES)
    with filter_col2:
        month_filter = st.selectbox("Filter by month", ["All"] + sorted(all_expenses["expense_date"].dt.strftime("%Y-%m").unique().tolist(), reverse=True))
    filtered = all_expenses.copy()
    if category_filter != "All":
        filtered = filtered[filtered["category"] == category_filter]
    if month_filter != "All":
        filtered = filtered[filtered["expense_date"].dt.strftime("%Y-%m") == month_filter]

    st.write("Tick the **Delete?** box for each expense you want to remove, then press Delete selected expenses.")
    editable = filtered[["id", "expense_date", "category", "description", "amount"]].copy()
    editable["expense_date"] = editable["expense_date"].dt.strftime("%Y-%m-%d")
    editable = editable.rename(columns={"id": "ID", "expense_date": "Date", "category": "Category", "description": "Description", "amount": "Amount (₹)"})
    editable.insert(0, "Delete?", False)
    edited = st.data_editor(
        editable, use_container_width=True, hide_index=True, key="expense_bulk_editor",
        disabled=["ID", "Date", "Category", "Description", "Amount (₹)"],
        column_config={"Delete?": st.column_config.CheckboxColumn("Delete?", help="Select expenses to delete", default=False)},
    )
    selected_ids = edited.loc[edited["Delete?"], "ID"].astype(int).tolist()
    if selected_ids:
        st.warning(f"{len(selected_ids)} expense(s) selected for deletion.")
    if st.button("Delete selected expenses", type="secondary", disabled=not selected_ids):
        delete_expenses(selected_ids)
        st.success(f"Deleted {len(selected_ids)} expense(s).")
        st.rerun()

    csv_data = filtered.drop(columns=["id"]).assign(expense_date=filtered["expense_date"].dt.strftime("%Y-%m-%d")).to_csv(index=False).encode("utf-8")
    st.download_button("Download filtered expenses as CSV", data=csv_data, file_name="spendsmart_expenses.csv", mime="text/csv")
else:
    st.write("Your saved expenses will appear here.")

st.caption("SpendSmart | Personal Expense Management System | Data is stored locally in expenses.db")
