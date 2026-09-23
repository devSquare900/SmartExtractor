# SmartExtractor

Upload contracts and invoices (PDF, PNG, JPG, TIFF). SmartExtractor pulls out the key fields
(customer, date, document number, amount, PO number) and line items, and shows where each value
came from on the page. You can then correct the values and export them as JSON or CSV.

- **Backend:** FastAPI + PaddleOCR + PyMuPDF, SQLite storage (`backend/`)
- **Frontend:** React + Vite (`frontend/`)

## Setup

### Backend

Requires Python 3.12 (the PaddlePaddle 2.6 wheels do not support 3.13).

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

On first start, any old `storage/ocr_results/*.json` files are imported into the SQLite database
(`storage/smartextractor.db`) and re-parsed. The JSON files are left in place.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env              # optional: change VITE_API_URL
npm run dev
```

Then open http://localhost:5173.

## Configuration

| Setting | Where | Default |
|---|---|---|
| Backend URL used by the frontend | `frontend/.env` → `VITE_API_URL` | `http://localhost:8000` |
| Allowed frontend origins (CORS) | env `ALLOWED_ORIGINS` (comma-separated) | `http://localhost:5173,http://127.0.0.1:5173` |
| Max upload size | env `MAX_UPLOAD_MB` | `25` |
| Storage folder | env `SMARTEXTRACTOR_STORAGE` | `backend/storage` |
| Field labels, keywords, date order, low-confidence threshold | `backend/config/fields.json` | — |

### Adding or changing fields

Edit `backend/config/fields.json`. Each field lists the labels to look for, compared in lowercase
with spaces removed, for example `"Invoice No."` becomes `invoiceno`. Labels are listed in priority order.
`match` is `exact` (the whole label must match) or `contains`. After you change
the file, press **Re-extract** on a document to parse it again. You do not need to restart the
server.

## How extraction works

1. PDF pages are rendered to images. If a page has a real text layer, its text is read directly.
   This is faster and more accurate than OCR. Scanned pages go through PaddleOCR.
2. The parser finds each label and takes the value from the same block (`Date: 12/03/2024`), to
   its right, or below it. Dates and amounts must contain a digit.
3. Dates are standardised to `YYYY-MM-DD`. Amounts become `1234.50` plus a currency when one is
   found.
4. Line items are grouped into rows and split into columns using the table header.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/upload` | Upload one file (call once per file) |
| GET | `/api/documents` | List documents |
| GET / DELETE | `/api/documents/{id}` | Get info / delete document and its files |
| GET / PUT | `/api/documents/{id}/extracted` | Get / save (edited) extracted data |
| POST | `/api/documents/{id}/reextract` | Re-run the parser (discards edits) |
| GET | `/api/documents/{id}/export?format=json\|csv` | Download extracted data |
| GET | `/api/documents/{id}/ocr` | Raw text blocks per page |
| GET | `/api/documents/{id}/images` | Page image URLs |
| GET | `/api/documents/{id}/file` | Original uploaded file |

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

The tests cover the parser, date and amount normalisation, and the API (upload validation, the
text-layer path, edit/save, export and delete). They don't need PaddleOCR to run.
