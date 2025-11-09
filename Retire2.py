
import streamlit as st
import pandas as pd
import numpy as np
import io
import plotly.graph_objects as go

st.set_page_config(layout="wide", page_title="Retirement Corpus Simulator (v5)")
st.title("Retirement Corpus Simulator — v5 (Grouped BASIS sidebar)")

# Default USD->INR in case BASIS doesn't provide it
DEFAULT_USD_TO_INR = 88.0

uploaded = st.file_uploader("Upload Excel (or leave blank to use included sample)", type=["xlsx"])
default_path = "/mnt/data/Retirement_Calc.xlsx"
xlsx_path = None
if uploaded is not None:
    xlsx_path = uploaded
else:
    xlsx_path = default_path

@st.cache_data
def load_excel(path):
    xlsx = pd.ExcelFile(path)
    sheets = {s: pd.read_excel(path, sheet_name=s) for s in xlsx.sheet_names}
    return sheets

sheets = load_excel(xlsx_path)
st.sidebar.header("Sheets detected")
for s in sheets:
    st.sidebar.write(f"- {s} ({sheets[s].shape[0]} rows x {sheets[s].shape[1]} cols)")

def norm_cols(df):
    dfc = df.copy()
    dfc.columns = [str(c).strip() for c in dfc.columns]
    return dfc

def read_basis_params(df):
    """"
    Expect BASIS sheet with first column=Parameter, second column=Value, optional third=Description.
    Returns ordered list of (param, value, description)
    """
    params = []
    if df is None or df.empty:
        return params
    dfc = norm_cols(df)
    cols = dfc.columns.tolist()
    key_col = cols[1] if len(cols)>1 else cols[0]
    val_col = cols[2] if len(cols)>2 else (cols[1] if len(cols)>1 else cols[0])
    desc_col = cols[3] if len(cols)>3 else None
    for _, r in dfc.iterrows():
        k = r.get(key_col)
        v = r.get(val_col) if val_col in r else None
        d = r.get(desc_col) if desc_col in r else None
        if pd.isna(k):
            continue
        params.append((str(k).strip(), v, str(d).strip() if pd.notna(d) else ""))
    return params

def group_param_name(name):
    ln = name.lower()
    if any(x in ln for x in ['india','indian','inr','bharat']):
        return '🇮🇳 Indian Parameters'
    if any(x in ln for x in ['us','usa','usd','america','american']):
        return '🇺🇸 US Parameters'
    return '🌐 General Parameters'

def create_sidebar_controls(params):
    # returns dict of param name -> value (user chosen)
    grouped = {}
    for name, val, desc in params:
        grp = group_param_name(name)
        grouped.setdefault(grp, []).append((name, val, desc))
    user_values = {}
    for grp in sorted(grouped.keys()):
        with st.sidebar.expander(grp, expanded=True):
            for (name, val, desc) in grouped[grp]:
                label = name
                help_txt = desc if desc else None
                # try numeric
                numeric = None
                if val is None or (isinstance(val, str) and val.strip()==""):
                    numeric = None
                else:
                    try:
                        numeric = float(val)
                    except:
                        numeric = None
                if numeric is not None:
                    # if value looks like percent in 0-100, use number_input with percent display
                    user_val = st.number_input(label, value=float(numeric), help=help_txt, step=0.1, format="%.4f")
                    user_values[name] = user_val
                else:
                    user_val = st.text_input(label, value=str(val) if val is not None else "", help=help_txt)
                    user_values[name] = user_val
    return user_values

def parse_basis_for_internal(vars_dict):
    """Extract some commonly used fields from the user-provided BASIS params dict"""
    usd_to_inr = None
    inflation = None
    # common keys to search
    for k,v in vars_dict.items():
        lk = k.lower()
        if ('usd' in lk or 'exchange' in lk or 'dollar' in lk) and ('inr' in lk or 'to' in lk):
            try:
                usd_to_inr = float(v)
            except:
                pass
        if 'usd to inr' in lk or 'usd->inr' in lk or 'usd to inr' in lk:
            try: usd_to_inr = float(v)
            except: pass
        if 'inflation' == lk or 'inflation (%)' in lk.lower() or 'inflation' in lk:
            # prefer Indian inflation if exact
            try:
                inflation = float(v)
            except:
                pass
    return usd_to_inr, inflation

def parse_basis_map(df):
    # map instrument name -> return % if present in basis sheet
    basis_map = {}
    if df is None or df.empty:
        return basis_map
    dfc = norm_cols(df)
    cols = dfc.columns.tolist()
    key_col = cols[1] if len(cols)>1 else cols[0]
    val_col = cols[2] if len(cols)>2 else (cols[1] if len(cols)>1 else cols[0])
    for _, r in dfc.iterrows():
        k = r.get(key_col); v = r.get(val_col) if val_col in r else None
        if pd.isna(k) or pd.isna(v): continue
        try:
            basis_map[str(k).strip()] = float(v)/100.0
        except:
            try:
                basis_map[str(k).strip()] = float(str(v).replace('%',''))/100.0
            except:
                continue
    return basis_map

def parse_investments(df, basis_map, usd_to_inr):
    dfc = norm_cols(df)
    cols = dfc.columns.tolist()
    name_col = None; principal_col = None; rate_col = None; currency_col = None
    for c in cols:
        lc = c.lower()
        if any(k in lc for k in ['instrument','investment','name']):
            name_col = c; break
    for c in cols:
        lc = c.lower()
        if any(k in lc for k in ['principal','amount','value']):
            principal_col = c; break
    for c in cols:
        lc = c.lower()
        if any(k in lc for k in ['rate','%','return']):
            rate_col = c; break
    for c in cols:
        if 'currency' in c.lower():
            currency_col = c; break
    investments = []
    if name_col is None:
        name_col = cols[1] if len(cols)>1 else cols[0]
    for _, r in dfc.iterrows():
        name = r.get(name_col)
        if pd.isna(name): continue
        principal = 0.0; rate = None; currency = None
        if principal_col and pd.notna(r.get(principal_col)):
            try: principal = float(r.get(principal_col))
            except: principal = 0.0
        else:
            for c in cols:
                v = r.get(c)
                try:
                    fv = float(v)
                    if fv>principal:
                        principal = fv
                except:
                    continue
        if rate_col and pd.notna(r.get(rate_col)):
            try:
                rate = float(str(r.get(rate_col)).replace('%',''))/100.0
            except:
                rate = None
        if currency_col and pd.notna(r.get(currency_col)):
            currency = str(r.get(currency_col)).strip().upper()
            if currency == 'USD' and usd_to_inr is not None:
                principal = principal * usd_to_inr
        rate_from_basis = None
        if isinstance(name, str):
            for k in basis_map:
                if k.lower() in name.lower():
                    rate_from_basis = basis_map[k]; break
        final_rate = rate_from_basis if rate_from_basis is not None else (rate if rate is not None else 0.0)
        investments.append({'name': str(name).strip(), 'principal': principal, 'rate': final_rate, 'currency': currency or 'INR'})
    inv_df = pd.DataFrame(investments)
    total_principal = inv_df['principal'].sum() if not inv_df.empty else 0.0
    weighted_rate = 0.0
    if total_principal>0:
        weighted_rate = (inv_df['principal'] * inv_df['rate']).sum() / total_principal
    return inv_df, total_principal, weighted_rate

def parse_expenditure(df, usd_to_inr):
    dfc = norm_cols(df)
    cols = dfc.columns.tolist()
    item_col = None; currency_col = None; year_col = None; freq_cols = {}
    for c in cols:
        lc = c.lower()
        if any(k in lc for k in ['item','expenditure','name']):
            item_col = c; continue
        if 'currency' in lc:
            currency_col = c; continue
        if 'year' == lc.strip() or 'year' in lc:
            year_col = c; continue
        if 'month' in lc:
            freq_cols['monthly'] = c; continue
        if 'quater' in lc or 'quarter' in lc:
            freq_cols['quarterly'] = c; continue
        if 'half' in lc:
            freq_cols['halfyear'] = c; continue
        if 'annual' in lc and 'one' not in lc:
            freq_cols['annual'] = c; continue
        if 'one' in lc or 'one time' in lc or 'one-time' in lc:
            freq_cols['one_time'] = c; continue
    if item_col is None:
        item_col = cols[1] if len(cols)>1 else cols[0]
    rows = []
    recurring_monthly_total = 0.0
    for _, r in dfc.iterrows():
        item = r.get(item_col)
        if pd.isna(item): continue
        currency = 'INR'
        if currency_col and pd.notna(r.get(currency_col)):
            currency = str(r.get(currency_col)).strip().upper()
        def conv_amount(a):
            try:
                v = float(a)
            except:
                return 0.0
            if currency == 'USD' and usd_to_inr is not None:
                return v * usd_to_inr
            return v
        monthly_amt = 0.0
        if 'monthly' in freq_cols and pd.notna(r.get(freq_cols['monthly'])):
            monthly_amt += conv_amount(r.get(freq_cols['monthly']))
        if 'quarterly' in freq_cols and pd.notna(r.get(freq_cols['quarterly'])):
            monthly_amt += conv_amount(r.get(freq_cols['quarterly']))/3.0
        if 'halfyear' in freq_cols and pd.notna(r.get(freq_cols['halfyear'])):
            monthly_amt += conv_amount(r.get(freq_cols['halfyear']))/6.0
        if 'annual' in freq_cols and pd.notna(r.get(freq_cols['annual'])):
            amt = conv_amount(r.get(freq_cols['annual']))
            rows.append({'item': str(item).strip(), 'type':'annual', 'amount': amt, 'year': None, 'currency': currency})
        if 'one_time' in freq_cols and pd.notna(r.get(freq_cols['one_time'])):
            amt = conv_amount(r.get(freq_cols['one_time']))
            y = None
            if year_col and pd.notna(r.get(year_col)):
                try:
                    y = int(r.get(year_col))
                except:
                    y = None
            rows.append({'item': str(item).strip(), 'type':'one_time', 'amount': amt, 'year': y, 'currency': currency})
        other_numeric = 0.0
        for c in cols:
            if c in [item_col, currency_col, year_col] + list(freq_cols.values()):
                continue
            v = r.get(c)
            if pd.notna(v):
                try:
                    fv = float(v)
                    other_numeric += fv
                except:
                    continue
        if other_numeric>0 and not ('monthly' in freq_cols and pd.notna(r.get(freq_cols.get('monthly','')))):
            monthly_amt += conv_amount(other_numeric)
        if monthly_amt>0:
            rows.append({'item': str(item).strip(), 'type':'monthly', 'amount': monthly_amt, 'year': None, 'currency': currency})
            recurring_monthly_total += monthly_amt
    exp_df = pd.DataFrame(rows)
    return exp_df, recurring_monthly_total

def simulate(inv_total, annual_rate, exp_df, start_age=52, end_age=80, monthly_inflation=0.0, start_calendar_year=2025):
    months = (end_age - start_age + 1) * 12
    dates = pd.date_range(start=f"{start_calendar_year}-01-01", periods=months, freq='MS')
    corpus = inv_total
    monthly_rate = annual_rate / 12.0
    corpus_list = []; income_list = []; expenditure_list = []
    spikes = {d:[] for d in dates}
    for _, r in exp_df.iterrows():
        typ = r['type']; amt = r['amount']; y = r['year'] if 'year' in r and not pd.isna(r['year']) else None; item = r['item']
        if typ == 'monthly':
            continue
        if typ == 'annual':
            for d in dates:
                if d.month == 12:
                    spikes[d].append((item, 'annual', amt))
        if typ == 'one_time':
            if y is not None:
                target = pd.Timestamp(year=int(y), month=12, day=1)
                if target in spikes:
                    spikes[target].append((item, 'one_time', amt))
            else:
                for d in dates:
                    if d.month == 12:
                        spikes[d].append((item, 'one_time', amt))
                        break
    monthly_recurring = exp_df.loc[exp_df['type']=='monthly','amount'].sum() if not exp_df.empty else 0.0
    for i, d in enumerate(dates):
        monthly_income = corpus * monthly_rate
        monthly_infl = (1+monthly_inflation)**i
        monthly_expenditure = monthly_recurring * monthly_infl
        spike_items = spikes.get(d, [])
        spike_total = sum([a[2] for a in spike_items]) if spike_items else 0.0
        monthly_expenditure += spike_total
        corpus = corpus + monthly_income - monthly_expenditure
        corpus_list.append(corpus); income_list.append(monthly_income); expenditure_list.append(monthly_expenditure)
    df_sim = pd.DataFrame({
        'date': dates,
        'age': np.linspace(start_age, end_age, len(dates)),
        'monthly_income': income_list,
        'monthly_expenditure': expenditure_list,
        'corpus': corpus_list
    })
    dec_rows = []
    for d in sorted(spikes.keys()):
        if d.month == 12 and spikes[d]:
            for it, typ, amt in spikes[d]:
                dec_rows.append({'Year': d.year, 'Item': it, 'Type': typ, 'Amount (INR)': amt})
    dec_df = pd.DataFrame(dec_rows)
    if not dec_df.empty:
        dec_summary = dec_df.groupby('Year', as_index=False)['Amount (INR)'].sum().rename(columns={'Amount (INR)':'Total_December_Amount (INR)'})
    else:
        dec_summary = pd.DataFrame(columns=['Year', 'Total_December_Amount (INR)'])
    return df_sim, spikes, dec_df, dec_summary

# Read BASIS parameters
basis_params = read_basis_params(sheets.get('BASIS', pd.DataFrame()))
# create sidebar controls grouped
user_basis = create_sidebar_controls(basis_params)

# derive usd->inr and inflation defaults from sidebar params if present
usd_to_inr, inflation_from_basis = parse_basis_for_internal(user_basis)
if usd_to_inr is None:
    usd_to_inr = user_basis.get('USD to INR', user_basis.get('USD→INR', user_basis.get('USD->INR', DEFAULT_USD_TO_INR)))
try:
    usd_to_inr = float(usd_to_inr)
except:
    usd_to_inr = DEFAULT_USD_TO_INR

if inflation_from_basis is None:
    # try to find keys with 'inflation' in name and take first numeric
    inflation_from_basis = None
    for k,v in user_basis.items():
        if 'inflation' in k.lower():
            try:
                inflation_from_basis = float(v)/100.0 if float(v)>1 else float(v)
                break
            except:
                continue
# if still none, leave None and allow sidebar numeric later
if inflation_from_basis is not None:
    st.sidebar.markdown(f"**Inflation (annual)** read from BASIS inputs: {inflation_from_basis*100:.2f}%")

# parse basis map for instrument returns
basis_map = parse_basis_map(sheets.get('BASIS', pd.DataFrame()))
inv_df, total_principal, weighted_rate = parse_investments(sheets.get('INVESTMENT', pd.DataFrame()), basis_map, usd_to_inr)
exp_df, recurring_monthly_total = parse_expenditure(sheets.get('EXPENDITURE', pd.DataFrame()), usd_to_inr)

st.subheader("Parsed inputs & assumptions (v5)")
st.markdown(f"- All values shown in INR (USD->INR = {usd_to_inr:.2f})")
st.markdown(f"- Total starting corpus (INR) = **{total_principal:,.2f}**")
st.markdown(f"- Weighted annual rate = **{weighted_rate*100:.2f}%**")
st.markdown(f"- Parsed recurring monthly total (INR) = **{recurring_monthly_total:,.2f}**")

st.write("### Parsed INVESTMENTS")
st.dataframe(inv_df)
st.write("### Parsed EXPENDITURE (rows)")
st.dataframe(exp_df)

st.sidebar.header("Simulation parameters (v5)")
start_age = st.sidebar.number_input("Start age (years)", value=52, min_value=18, max_value=120)
end_age = st.sidebar.number_input("End age (years)", value=80, min_value=start_age, max_value=120)

# If inflation_from_basis present, use it; else provide sidebar numeric input as percent
if inflation_from_basis is not None:
    annual_infl = inflation_from_basis
else:
    annual_infl = st.sidebar.number_input("Annual inflation (%)", value=0.0, step=0.1)/100.0
monthly_inflation = (1+annual_infl)**(1/12.0)-1.0

start_calendar_year = st.sidebar.number_input("Simulation start calendar year (e.g. 2026)", value=2025, step=1)
show_spikes = st.sidebar.checkbox("Highlight December spikes on plot", value=True)

df_sim, spikes, dec_df, dec_summary = simulate(total_principal, weighted_rate, exp_df, start_age=start_age, end_age=end_age, monthly_inflation=monthly_inflation, start_calendar_year=start_calendar_year)

st.write("### Simulation snapshot (first 12 rows)")
st.dataframe(df_sim.head(12))

# Interactive Plotly chart (monthly)
fig = go.Figure()
fig.add_trace(go.Scatter(x=df_sim['date'], y=df_sim['monthly_expenditure'], mode='lines', name='Monthly Expenditure'))
fig.add_trace(go.Scatter(x=df_sim['date'], y=df_sim['monthly_income'], mode='lines', name='Monthly Income'))
fig.add_trace(go.Scatter(x=df_sim['date'], y=df_sim['corpus'], mode='lines', name='Cumulative Corpus'))

if show_spikes:
    spike_dates = [d for d in sorted(spikes.keys()) if d.month==12 and spikes[d]]
    spike_vals = [df_sim.loc[df_sim['date']==d,'monthly_expenditure'].values[0] for d in spike_dates]
    fig.add_trace(go.Scatter(x=spike_dates, y=spike_vals, mode='markers+text', name='December spikes', text=[f"{v:,.0f}" for v in spike_vals], textposition="top center"))

fig.update_layout(title=f'Age {start_age} → {end_age} : Monthly Expenditure, Income, Cumulative Corpus (v5)', yaxis_title='INR', hovermode='x unified')
st.plotly_chart(fig, use_container_width=True)

st.subheader("December itemized calendar view (INR)")
if dec_df.empty:
    st.write("No December lump-sum expenditures detected in simulation range.")
else:
    st.write("Itemized December expenditures (each row = a payment in December)")
    st.dataframe(dec_df)
    st.write("December totals by year")
    st.dataframe(dec_summary)

    # Provide download buttons for CSVs
    csv_buf = io.StringIO()
    df_sim.to_csv(csv_buf, index=False)
    st.download_button("Download full monthly simulation CSV", data=csv_buf.getvalue(), file_name="simulation_results_v5.csv", mime="text/csv")

    csv_buf2 = io.StringIO()
    dec_df.to_csv(csv_buf2, index=False)
    st.download_button("Download itemized December spikes CSV", data=csv_buf2.getvalue(), file_name="december_spikes_v5.csv", mime="text/csv")

    csv_buf3 = io.StringIO()
    dec_summary.to_csv(csv_buf3, index=False)
    st.download_button("Download December totals summary CSV", data=csv_buf3.getvalue(), file_name="december_spikes_summary_v5.csv", mime="text/csv")

st.success("v5 simulation complete. Graphs are shown above and downloadable CSVs are available.")
