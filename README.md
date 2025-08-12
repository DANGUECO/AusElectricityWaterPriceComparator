# Scenario

💧 Why This App Matters
In Australia, water pricing isn’t standardised — it varies by region, postcode, and provider. Two households using the same amount of water could be paying vastly different annual bills simply because they fall under different water utilities.

For most people, comparing these prices means trawling through multiple provider websites, interpreting complicated tariff tables, and manually calculating costs based on their usage. This process is slow, confusing, and prone to error — meaning many customers never find out if they’re overpaying.

The Australian Water Price Comparator solves this problem instantly.

Enter your postcode and annual water usage.

Get a clear side-by-side comparison of all providers in your area.

See exact annual costs, fixed and usage charges, tariff structures, and notes.

Make informed decisions in seconds, without spreadsheets or manual research.

# What This App Does
Takes your inputs: postcode and annual water use (kL).

Finds matching providers for that postcode (from the sample mapping in your Python file).

Calculates an estimated annual bill for each provider using built-in 2025–26 tariffs:

Adds fixed charges (water network + sewerage).

Adds usage charges based on your kL:

Flat rate → kL × rate.

Two-step/block tariff → splits usage at the block limit (160.066 kL by default; Icon Water ~200 kL/year).

Shows results in a table with fixed charges, usage rates, notes/assumptions, and the total estimate.

Highlights the cheapest option at your chosen usage.

Compares multiple usage levels (e.g., 160 vs 200 kL) on a quick chart to show how costs change.

Lets you download the table as CSV.

Can refresh tariff data via the Refresh tariffs button, which calls your scraping stub refresh_provider_data(). When you add more scrapers, this will pull fresh numbers.

# What It’s For
A quick, like-for-like annual bill comparison between the suppliers that serve a postcode.

# Made With
PyCharm • Python • Command Prompt • AI Agent • Streamlit

# How to run the Water Price app (Windows) — every time
Open the project folder

<img width="675" height="263" alt="image" src="https://github.com/user-attachments/assets/b96dc265-4132-43b0-aeb9-b78318dcb65a" />

Go to: C:\Users\User\Desktop\water-price-app

Click the address bar, type cmd, press Enter (opens Command Prompt in this folder)

Activate the virtual environment

type Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass (bypasses to allow scripting on cmd)

then type .venv\Scripts\activate (activates virtual environment)

then type streamlit run streamlit_app.py (activates local host)

Then the app should run :) !

# The output tab will open like this:

<img width="2516" height="1172" alt="image" src="https://github.com/user-attachments/assets/9966ad2b-578b-469e-9fcd-821242cf8918" />

Note: if you want the virtual environment to stop running type Ctrl+C




