# 📞 TeleSign PhoneID Batch Script

This repository provides an **example Python script** that demonstrates how to run **TeleSign’s PhoneID API** in batch format.  
It supports multiple add-ons, concurrency control, and built-in rate limiting (`--tps-limit`) to help you stay within your account’s TPS (transactions per second) limits.

---

## ⚙️ Overview

The script reads a list of phone numbers from a `.csv` or `.txt` file and performs batch lookups against the **TeleSign PhoneID** endpoint:

```
POST https://rest-ww.telesign.com/v1/phoneid/{complete_phone_number}
```

You can specify which **add-ons** to include (for example `contact`, `porting_history`, or `number_deactivation`).

If `"live"` is included in the add-ons list, the script automatically uses the **PhoneID Live** endpoint:

```
GET https://rest-ww.telesign.com/v1/phoneid/live/{complete_phone_number}
```

---

## 🧩 Features

✅ Reads `.csv` or `.txt` input  
✅ Automatically skips headers (e.g., `phone_number`)  
✅ Cleans phone numbers to digits-only format  
✅ Validates length (8–15 digits)  
✅ Supports add-ons like `contact`, `number_deactivation`, `porting_history`, etc.  
✅ Built-in **TPS limiter** to avoid API throttling  
✅ Concurrent requests with automatic retries and backoff  
✅ Outputs a `.csv` file with response JSON for each number  

---

## 📦 Requirements

- Python **3.7+**
- Library: `requests`

Install dependencies:
```bash
pip install requests
```

---

## 🔐 Authentication

Export your TeleSign credentials as environment variables.

### macOS / Linux
```bash
export TELE_SIGN_CUSTOMER_ID="your_customer_id"
export TELE_SIGN_API_KEY="your_api_key"
```

### Windows PowerShell
```powershell
$env:TELE_SIGN_CUSTOMER_ID="your_customer_id"
$env:TELE_SIGN_API_KEY="your_api_key"
```

> ⚠️ If you used `setx`, open a **new PowerShell window** for the change to take effect.

---

## 🧾 Input File Format

You can use either `.csv` or `.txt`.  
The first column (or line) must contain phone numbers.

### Example: `phones.csv`
```csv
phone_number
15555550100
12065918829
14243833558
```

The script automatically:
- Ignores the header row
- Strips symbols like `+`, `()`, `-`, and spaces
- Ensures only valid digits (8–15)

---

## 🚀 Usage Examples

### Standard PhoneID (POST)
```bash
python telesign_phoneid_batch.py phones.csv   --addons contact,porting_history,number_deactivation   --ucid BACF   --tps-limit 5   --concurrency 10   --out results.csv
```

Request body format:
```json
{
  "addons": {
    "contact": {},
    "number_deactivation": {},
    "porting_history": {}
  },
  "ucid": "BACF"
}
```

### PhoneID Live (GET)
When `live` is listed in `--addons`, the script automatically calls the `/live/` endpoint:
```bash
python telesign_phoneid_batch.py phones.csv   --addons live   --ucid BACF   --tps-limit 3   --out results_live.csv
```

---

## ⚖️ TPS Limiting

To prevent rate-limit errors, use `--tps-limit` to cap requests per second.

```bash
python telesign_phoneid_batch.py phones.csv   --addons contact,porting_history   --tps-limit 5   --concurrency 10
```

This guarantees that no more than 5 requests per second are sent across all threads.

---

## ⚙️ Additional Options

| Option | Description |
|--------|--------------|
| `--ucid` | Optional UCID (Use Case ID) |
| `--tps-limit` | Limit total requests per second |
| `--concurrency` | Number of parallel requests |
| `--max-retries` | Retries on 429 or 5xx |
| `--backoff` | Exponential backoff base seconds |
| `--timeout` | Per-request timeout seconds |
| `--out` | Output CSV file |
| `--min-digits` / `--max-digits` | Min/max digits for validation |
| `--no-skip-invalid` | Don’t skip invalid numbers |
| `--proxy` | Proxy URL (HTTP/HTTPS) |

---

## 📊 Output

The script produces a CSV file with:

| phone | status_code | status_description | json |
|-------|--------------|--------------------|------|
| 15555550100 | 200 | Transaction successfully completed | `{...full JSON...}` |
| 12065918829 | 400 | Invalid value | `{...error JSON...}` |

---

## 🧠 Tips & Common Issues

**Invalid value (400)**  
→ Usually caused by non-digit characters, hidden BOMs, or bad CSV headers.  
Ensure your input file is UTF-8 (no BOM) and contains only digits.

**Missing env var**  
→ Use `$env:` instead of `setx` in the same PowerShell window (see above).

**1.42E+10 in Excel**  
→ Excel auto-formats large numbers. When editing, import the CSV as “Text” column type.

---

## ⚠️ Disclaimer and Warranty Notice

> **Disclaimer:**  
> This script is provided **“as is”** for demonstration purposes only.  
> **TeleSign does not provide, support, or guarantee** this script and makes **no representations or warranties** of any kind, express or implied, including but not limited to warranties of merchantability, fitness for a particular purpose, or non-infringement.  
>  
> TeleSign shall **not be liable** for any damages or losses, including but not limited to direct, indirect, incidental, consequential, or punitive damages, arising from or related to the use, modification, or execution of this script.  
>  
> By using this example, you acknowledge that you are **solely responsible** for understanding how it works, reviewing the source code, testing it in a controlled environment, and ensuring that it meets your operational and compliance requirements.  
>  
> Use this script entirely **at your own risk.**

---

## 🧩 Suggested Workflow

1. Clone this repo or download `telesign_phoneid_batch.py`
2. Install dependencies (`pip install requests`)
3. Set your environment variables
4. Prepare your `phones.csv`
5. Run the script using `--addons` and `--tps-limit`
6. Review `results.csv` for API responses

---

## 📄 License

This code example is **not licensed nor intended for production use** and is provided solely for educational and testing purposes.  

---
