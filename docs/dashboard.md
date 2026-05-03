# Lead Review Dashboard

Autobots includes a simple local Streamlit dashboard for reviewing processed leads before manual outreach.

The dashboard does not send WhatsApp messages. It only helps inspect leads, read suggested messages, open generated `wa.me` links manually, and update local lead status in the CSV.

## Run The Dashboard

Install dependencies:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Start Streamlit:

```bash
.venv/bin/streamlit run src/autobots/dashboard/lead_review_app.py
```

Streamlit will print a local browser URL, usually:

```text
http://localhost:8501
```

## Prepare A Processed CSV

The dashboard reads CSV files from:

```text
data/processed/
```

Generate one with the lead pipeline:

```bash
.venv/bin/python src/scripts/process_leads.py \
  --input data/raw/real_estate_leads.csv \
  --output data/processed/top_real_estate_leads.csv \
  --niche real_estate \
  --limit 100
```

## Expected Columns

The dashboard works best with CSV files containing:

```text
name
phone
normalized_phone
category
city
source_url
score
priority
score_reasons
suggested_message
whatsapp_link
status
```

If the `status` column is missing, the dashboard treats leads as `new` and adds the column when saving.

## Filters

Available filters:

- niche
- priority
- city
- score range
- status

If the CSV does not include a `niche` column, the app infers the niche from the filename. For example:

```text
top_real_estate_leads.csv
```

will be treated as `real_estate`.

## Status Values

You can update a lead to:

```text
new
contacted
replied
interested
demo_sent
closed
lost
do_not_contact
```

Click `Save updated CSV` to write the new status back to the selected file.

## Important Safety Notes

- Do not commit real processed lead CSV files.
- Keep `data/processed/` for local working data.
- The dashboard opens WhatsApp links manually; it does not automate outbound messages.
- Use this dashboard to review and prioritize leads before contacting them.
