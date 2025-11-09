
Retirement Corpus Simulator - v5
================================

What's new in v5:
- Dynamic grouped BASIS sidebar controls: all parameters in the BASIS sheet are shown as editable sidebar inputs.
  - Parameters are auto-grouped into: 🇮🇳 Indian Parameters, 🇺🇸 US Parameters, 🌐 General Parameters.
  - Numeric values become number_inputs, text values become text_inputs.
  - Values in the sidebar are used directly in simulation (user can override).
- Interactive monthly Plotly graph shown in-app.
- December itemized calendar view (INR only) and downloadable CSVs.
- USD->INR conversion pulled from BASIS (if present) or default 88.

How to use:
1. pip install -r requirements.txt
2. streamlit run app.py
3. Upload your Excel or use the included sample.
4. Edit BASIS assumptions in the sidebar; simulation updates automatically.
