# AusElectricityWaterPriceComparator
What this app does
Takes your inputs: you type a postcode and your annual water use (kL).

Finds the matching providers for that postcode (from the sample mapping in your Python file).

Calculates an estimated annual bill for each provider using your built-in 2025–26 tariffs:

Adds up fixed charges (water network + sewerage).

Adds usage charges based on your kL:

If it’s a flat rate, it’s simply kL × rate.

If it’s a two-step/block tariff, it splits usage at the block limit (160.066 kL by default; Icon Water uses ~200 kL/year).

Shows the results in a table with fixed charges, usage rates, notes/assumptions, and the total estimate.

Highlights the cheapest option at your chosen usage.

Lets you compare multiple usage levels (e.g., 160 vs 200 kL) on a quick chart to see how costs change.

Lets you download the table as CSV.

Can refresh tariff data via your “Refresh tariffs” button, which calls your scraping stub (refresh_provider_data()). When you add more scrapers, this button will pull fresh numbers.

What it’s for:
A quick like-for-like annual bill comparison between the suppliers that serve a postcode.
