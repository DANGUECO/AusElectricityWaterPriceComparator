# Scenario

💧 Why This App Matters
In Australia, water pricing isn’t standardised — it varies by region, postcode, and provider. Two households using the same amount of water could be paying vastly different annual bills simply because they fall under different water utilities.

For most people, comparing these prices means trawling through multiple provider websites, interpreting complicated tariff tables, and manually calculating costs based on their usage. This process is slow, confusing, and prone to error — meaning many customers never find out if they’re overpaying.

The Australian Water Price Comparator solves this problem instantly.

🧩 How to use (2 minutes)

Enter postcodes + annual usage (e.g., 160 kL).

See Cheapest option per postcode. Click “Explain” to see the exact math.

Optional: open Cost curves to compare providers across a usage range.

Top tiles show overall health (OK/STALE/etc).

Check Provider health, Incidents, and Run logs for operational visibility.

# Test if you want
https://share.streamlit.io/user/dangueco 

# Explainability (why trust the numbers?)

For each postcode/provider/usage we show:

Line items:

Fixed = water + sewerage

Usage Tier 1 = rate × kL up to threshold

Usage Tier 2 = higher rate × excess kL (if any)

Threshold (kL/yr), FY, Last data updated, and Notes.

# Data & compliance

No live scraping in this repo. You maintain tariffs in code.

Update FY/“last updated” via the sidebar.

You can export updated data structures with export_python(...) (backend provides a snippet to paste back).

# FAQ 

Why is something “Incomplete”? It’s a placeholder (zeros). Fill the tariff.

Why “Stale”? Last check exceeded the SLA window. Hit Refresh or enable the scheduler.

Can I bulk compare? Yes — paste many postcodes, the table shows the cheapest for each.

Where’s the data stored? In code (PROVIDERS) + state in ops_state.json.

Can we add alerts? Yes—easy to add a Slack webhook where incidents open.

# Made With
PyCharm • Python • Command Prompt • AI Agent • Streamlit

# Tutorial: if you want to run it and change the code to your liking:

Run it locally (2 min)
Windows (PowerShell)

Open the project folder → type powershell in the address bar → Enter

Create + activate venv

python -m venv .venv
.\.venv\Scripts\Activate.ps1


If you see “running scripts is disabled”, run this once per session:

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1


Install deps

pip install -r requirements.txt
(or) pip install streamlit altair pandas


Run the app

streamlit run streamlit_app.py


Stop = Ctrl+C. Deactivate venv = deactivate.

Then the app should run :) !


# The output tab will open like this:

<img width="2026" height="1014" alt="image" src="https://github.com/user-attachments/assets/d3061d32-be47-4473-9f69-a7353b9dcf39" />

<img width="1537" height="573" alt="image" src="https://github.com/user-attachments/assets/e849e341-718c-414a-a930-4e4e920ef997" />

<img width="1534" height="574" alt="image" src="https://github.com/user-attachments/assets/48ed9a1b-f7d6-4d69-a0d3-e88d9aa9495d" />

# Incident Tracking

<img width="1533" height="765" alt="image" src="https://github.com/user-attachments/assets/d6cce5a5-184a-44ba-bbdc-7dabe766fdd3" />

# RUn logs

<img width="1494" height="602" alt="image" src="https://github.com/user-attachments/assets/54cc9e57-cdce-42da-ac2a-7517a3f00612" />

# Glossary

<img width="805" height="401" alt="image" src="https://github.com/user-attachments/assets/dd0bf785-90cc-459e-843b-d5b1f343bcf1" />

#video summary

https://github.com/user-attachments/assets/267191f9-6d2e-4ca8-9032-ed1be40f5db8

