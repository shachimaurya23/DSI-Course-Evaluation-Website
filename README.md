# Columbia Course Evaluation Dashboard

A Streamlit dashboard that reads course evaluation responses from a Google Sheet and surfaces difficulty/usefulness ratings, professor breakdowns, AI-generated comment summaries, and core-vs-elective views.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml with your real values

streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub.
2. Go to https://share.streamlit.io, sign in with GitHub, click **New app**.
3. Pick this repo, branch `main`, main file `app.py`.
4. Open **Advanced settings → Secrets** and paste the contents of your local `.streamlit/secrets.toml`.
5. Deploy.

## Secrets

All credentials live in `.streamlit/secrets.toml` (gitignored). See `.streamlit/secrets.toml.example` for the schema. Required keys: `sheet_id`, `worksheet_name`, `[gcp_service_account]`. Optional: `HF_API_TOKEN` for AI summaries.

The Google service account needs Editor access to the target sheet — share the
sheet with the service account's `client_email`. The app reads the original
form responses and appends approved reviews to this same worksheet.

## Student reviews and approvals

The **Submit Review** tab saves submissions as `Pending` to a local SQLite
database. Only approved reviews appear in **Student Reviews**. No Google Sheets
permissions or email service are used to store pending reviews; approval
appends a corresponding row to the existing course-response worksheet so the
dashboard's visualizations use it.

Approved reviews are written only to the existing form-response columns:
course, optional `Course Name` (when `Other` is selected), assignment and
assessment types, professor, semester, difficulty, usefulness, liked, and
comments. No columns are added or changed. The Google service account therefore
needs **Editor** access to the source spreadsheet.

Set `review_admin_emails` in Streamlit secrets to the exact Google account
addresses allowed to approve reviews. Admins sign in with Google using
`[auth]` for shared settings and `[auth.google]` for the Google provider
credentials; the approval tab is shown only to allowlisted accounts. General
dashboard sign-in remains controlled separately by `enable_auth`.

Install the dependencies from `requirements.txt` so Streamlit's `auth` extra
and Authlib are available for Google sign-in.

The database defaults to `reviews.sqlite3` beside `app.py`; set
`review_database_path` to use a different writable path. The database file is
ignored by Git. A local SQLite file is suitable for a single persistent app
server, but Streamlit Community Cloud does not guarantee local-file persistence
across restarts or redeployments. Use a host with a persistent disk or back up
the database if reviews must survive those events.

## AI summary reuse

Successful AI text is cached on the app server's local disk without a daily
expiry. Review summaries reuse the same response when comments are unchanged,
including when sheet rows are reordered or only ratings change. Rating-based
template text is computed from current data. Added, edited, or removed comments
change the AI input; review filters that change the comment set do too.

Each successful section is saved separately, so a failed section can retry
without regenerating the others. Unavailable responses are held only in memory
for five minutes to avoid repeated requests; a later visit can retry. Existing
quote and structured-data fallbacks remain in use. Comparisons also reuse saved
AI text, but refresh when the ratings or sampled comments in their prompt change.

This cache adds no paid service. It does not make inference free or change the
configured AI provider. Local disk storage is not a durable backup: a cache clear
or a Cloud rebuild that replaces the server disk can remove saved responses.

Run the cache regression checks without making AI requests:

```bash
python -m unittest discover -s tests -v
```
