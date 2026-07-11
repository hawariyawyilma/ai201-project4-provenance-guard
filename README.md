# FitFindr

A multi-tool AI agent that helps users find secondhand clothing and figure out how to wear it. Built for CodePath AI201 Project 2.

---

## Setup

```bash
# Clone and enter the repo
git clone https://github.com/hawariyawyilma/ai201-project2-fitfindr-starter.git
cd ai201-project2-fitfindr-starter

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Create .env file with your Groq API key
echo GROQ_API_KEY=your_key_here > .env

# Run the app
python app.py
```

Open the URL shown in your terminal (usually http://localhost:7860).

---

## Tool Inventory

### `search_listings(description, size, max_price)`
Searches the mock listings dataset and returns matching items sorted by keyword relevance.

| Parameter | Type | Description |
|-----------|------|-------------|
| `description` | str | Natural language item description (e.g., "vintage graphic tee") |
| `size` | str or None | Size filter (e.g., "M", "S/M"). Case-insensitive partial match. None = no filter. |
| `max_price` | float or None | Maximum price inclusive. None = no filter. |

**Returns:** List of listing dicts sorted by relevance score. Each dict contains: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand`, `platform`. Returns `[]` if no matches — never raises.

---

### `suggest_outfit(new_item, wardrobe)`
Calls the Groq LLM to suggest 1–2 complete outfit combinations using the thrifted item and the user's wardrobe.

| Parameter | Type | Description |
|-----------|------|-------------|
| `new_item` | dict | A listing dict for the item being considered |
| `wardrobe` | dict | Wardrobe dict with an `items` key (list of wardrobe item dicts). May be empty. |

**Returns:** Non-empty string with outfit suggestions. If the wardrobe is empty, returns general styling advice instead of wardrobe-specific combinations.

---

### `create_fit_card(outfit, new_item)`
Calls the Groq LLM to generate a 2–4 sentence Instagram/TikTok-style caption for the outfit.

| Parameter | Type | Description |
|-----------|------|-------------|
| `outfit` | str | Outfit suggestion string from `suggest_outfit()` |
| `new_item` | dict | Listing dict for the thrifted item (used for title, price, platform) |

**Returns:** Casual caption string mentioning the item name, price, and platform. Returns a descriptive error string if `outfit` is empty — never raises.

---

## How the Planning Loop Works

The planning loop in `run_agent()` follows conditional logic — it does not call all three tools unconditionally:

1. **Parse** the query using regex to extract `description`, `size`, and `max_price`.
2. **Search** — call `search_listings()` with the parsed parameters.
3. **Branch on results:**
   - If `results` is **empty** → set `session["error"]` with a message naming the filters applied and how to adjust them → **return early**. `suggest_outfit` is never called with empty input.
   - If `results` is **non-empty** → set `session["selected_item"] = results[0]` and continue.
4. **Suggest outfit** — call `suggest_outfit(selected_item, wardrobe)`.
5. **Create fit card** — call `create_fit_card(outfit_suggestion, selected_item)`.
6. Return the completed session.

The agent's behavior is genuinely different depending on what `search_listings` returns. An impossible query (designer ballgown under $5 in XXS) terminates after step 3 and the LLM tools are never called.

---

## State Management

All state lives in a single `session` dict, initialized fresh per query. Fields are written once and read by the next step — no values are re-entered by the user between tool calls:

- `session["parsed"]` — written after query parsing, used for search call
- `session["search_results"]` — written after search, checked for emptiness before proceeding
- `session["selected_item"]` — written as `results[0]`, passed directly into `suggest_outfit` and `create_fit_card` as the same dict object
- `session["outfit_suggestion"]` — written after `suggest_outfit`, passed directly into `create_fit_card`
- `session["fit_card"]` — written after `create_fit_card`, read by `app.py` for display
- `session["error"]` — written on early termination, checked by `app.py` before reading other fields

---

## Error Handling

### `search_listings` — No results
**Trigger:** Query like "designer ballgown size XXS under $5" matches nothing in the dataset.

**Agent response:** Sets `session["error"]` to a message like: *"No listings found for 'designer ballgown' with size XXS and under $5. Try broadening your search — remove the size or price filter, or use different keywords."* Returns the session immediately. `suggest_outfit` is never called.

**Tested with:**
```
python -c "from tools import search_listings; print(search_listings('designer ballgown', size='XXS', max_price=5))"
# Output: []
```

### `suggest_outfit` — Empty wardrobe
**Trigger:** User selects "Empty wardrobe (new user)" in the UI.

**Agent response:** The tool detects `wardrobe['items']` is empty and switches to a general styling prompt: *"They don't have a saved wardrobe yet. Give them 1-2 outfit ideas using general wardrobe staples..."* Returns a non-empty string with general advice — never crashes.

**Tested with:**
```
python -c "
from tools import search_listings, suggest_outfit
from utils.data_loader import get_empty_wardrobe
results = search_listings('vintage graphic tee', size=None, max_price=50)
print(suggest_outfit(results[0], get_empty_wardrobe()))
"
```

### `create_fit_card` — Empty outfit string
**Trigger:** Called with an empty or whitespace-only outfit string.

**Agent response:** Returns immediately with: *"Error: No outfit suggestion available to generate a fit card. Please try searching again."* Never calls the LLM, never raises an exception.

**Tested with:**
```
python -c "
from tools import search_listings, create_fit_card
results = search_listings('vintage graphic tee', size=None, max_price=50)
print(create_fit_card('', results[0]))
"
```

---

## Spec Reflection

**One way the spec helped:** Designing the planning loop logic in plain English before writing code made the branching condition obvious — "if results is empty, stop" is easy to miss when thinking in code, but impossible to miss when written out as a decision point in the architecture diagram.

**One way implementation diverged from the spec:** The spec suggested using the LLM to parse the query (extracting description, size, price from natural language). In practice, regex parsing was faster, cheaper (no extra LLM call per query), and more reliable for structured fields like price and size. The LLM was reserved for the tools that genuinely needed generation — outfit suggestion and fit card creation.

---

## AI Usage

**Instance 1 — search_listings implementation:**
I gave Claude the function stub from tools.py (the full docstring including Args, Returns, and TODO steps) plus the listings.json field names. I asked it to implement the scoring logic using keyword overlap. Before using the output, I verified that it filtered by all three parameters independently, handled the case where all three are None, and returned `[]` rather than raising when no listings matched. I added the `try/except` around `load_listings()` myself as an extra guard.

**Instance 2 — planning loop implementation:**
I gave Claude the architecture diagram from planning.md and the run_agent() TODO comments from agent.py. I asked it to implement the function following the numbered steps. I reviewed the generated code and confirmed it branched on empty results before calling suggest_outfit (not after), stored values in the session dict (not local variables), and returned early on error without calling downstream tools. I also added the `_parse_query()` helper myself since the original generated code used a simple split that missed price/size extraction reliably.
