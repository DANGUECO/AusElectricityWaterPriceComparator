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

Use Refresh now to validate everything, or Enable scheduler for automatic checks.

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
Open the project folder

Go to: C:\Users\User\Desktop\water-price-app

Click the address bar, type cmd, press Enter these commands (opens Command Prompt in this folder)

1.  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass (bypasses to allow scripting on cmd)

2. .venv\Scripts\activate (activates virtual environment)

3. streamlit run streamlit_app.py (activates local host)

4. Note: if you want the virtual environment to stop running type Ctrl+C

Then the app should run :) !


# The output tab will open like this:

# Cost curve

<img width="2026" height="1014" alt="image" src="https://github.com/user-attachments/assets/d3061d32-be47-4473-9f69-a7353b9dcf39" />

# Provider health 

<img width="1534" height="574" alt="image" src="https://github.com/user-attachments/assets/48ed9a1b-f7d6-4d69-a0d3-e88d9aa9495d" />

# Incident Tracking

<img width="1533" height="765" alt="image" src="https://github.com/user-attachments/assets/d6cce5a5-184a-44ba-bbdc-7dabe766fdd3" />

# RUn logs

<img width="1494" height="602" alt="image" src="https://github.com/user-attachments/assets/54cc9e57-cdce-42da-ac2a-7517a3f00612" />

# Glossary

<img width="805" height="401" alt="image" src="https://github.com/user-attachments/assets/dd0bf785-90cc-459e-843b-d5b1f343bcf1" />





