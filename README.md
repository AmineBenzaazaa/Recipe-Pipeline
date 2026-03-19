
# Run it
 source .venv/bin/activate && streamlit run pipeline_ui.py

The UI now has two routes:
- `/` for the existing Pins pipeline
- `/keywords` for keyword research + AI selection pipeline
- In `/keywords`, each line is treated as one keyword phrase by default (including commas).  
  Use Advanced `Keyword context hint` (example: `for dogs`) to improve research targeting.
- `/keywords` supports keyword-only generation (no source URL).  
  The generator can now build recipe rows directly from AI when URLs are missing.
- `/keywords` includes `Skip web research (AI from keywords only)` for pure keyword-driven generation.

Output language control:
- Configure per-website language rules directly in the UI under `Output Language Rules`.
- Save rules to persist into `.env` (`OUTPUT_LANGUAGE`, `DEFAULT_OUTPUT_LANGUAGE`, `SITE_LANGUAGE_MAP`, `SITE_LANGUAGE_MAP_FILE`).
- Per-site rules are also saved locally to `.secrets/site_language_map.json`.
- The generator resolves language from those rules for every run.


 cd /Users/useraccount/Documents/Blogging/RecipePipeline
  source .venv/bin/activate
  python sheet_image_worker.py \
    --sheet-tab Yumetry.com \
    --status-column Ready \
    --watch \
    --poll-seconds 20 \
    --log-level INFO

# Cleanup stale ImagineAPI jobs (dry-run first, then apply)
python scripts/cleanup_stale_imagine_jobs.py --older-than-minutes 120
python scripts/cleanup_stale_imagine_jobs.py --older-than-minutes 120 --apply

# Recipe Pipeline Batch Generator

Production-ready script to extract recipe data, FAQs, and image prompts into a CSV row per recipe.

## Setup

Python 3.12 is required. Python 3.13 currently fails to install dependencies because `pydantic-core`
does not yet support 3.13.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install  # required for midjourney_engine
```

Create a `.env` file (optional):

```
OPENAI_API_KEY=your_key_here
SERPER_API_KEY=your_serper_key_here
SERPAPI_API_KEY=your_serpapi_key_here
STYLE_ANCHOR=soft natural light, shallow depth of field, editorial food photography, high detail, 85mm
MODEL_NAME=gpt-4.1
VISION_MODEL=gpt-4.1
TEMPERATURE=0.6
TARGET_WORDS=1800
USE_MULTI_CALL=true
REQUEST_TIMEOUT=30
MAX_RETRIES=3
ACCEPT_LANGUAGE=
PIN_ACCEPT_LANGUAGE=
DEFAULT_OUTPUT_LANGUAGE=en
SITE_LANGUAGE_MAP=gotujka.pl:pl
SITE_LANGUAGE_MAP_FILE=.secrets/site_language_map.json
OUTPUT_LANGUAGE=
ENABLE_MODEL_FALLBACK=false
PRIMARY_MODEL_NAME=
FALLBACK_MODEL_NAME=
MODEL_FALLBACK_MIN_RECIPE_CHARS=900
MODEL_FALLBACK_MIN_FAQ_COUNT=4
SLEEP_SECONDS=1
IMAGE_MODEL=gpt-image-1
IMAGE_QUALITY=high
IMAGE_ENGINE=midjourney
GENERATE_IMAGES=false
USE_VISION_PROMPTS=false
SKIP_METADATA_ENRICHMENT=true
SKIP_GPT_FAQS=true
IMAGE_OUTPUT_DIR=generated_images
CLOUDINARY_URL=cloudinary://api_key:api_secret@cloud_name
CLOUDINARY_UPLOAD_PRESET=
CLOUDINARY_FOLDER=recipe-pipeline
IMAGINE_API_URL=http://localhost:8055
IMAGINE_API_TOKEN=your_imagineapi_token
IMAGINE_API_POLL_SECONDS=5
IMAGINE_API_TIMEOUT_SECONDS=600
IMAGINE_API_AUTO_START=false
IMAGINE_API_STARTUP_TIMEOUT_SECONDS=120
DISCORD_EMAIL=your_discord_email
DISCORD_PASSWORD=your_discord_password
MIDJOURNEY_HEADLESS=false
MIDJOURNEY_AUTO_FALLBACK_HEADFUL=true
MIDJOURNEY_TIMEOUT_SECONDS=300
MIDJOURNEY_PROFILE_DIR=.playwright/discord-profile
MIDJOURNEY_COOKIES_FILE=midjourney_cookies.json
MIDJOURNEY_STORAGE_STATE=
MIDJOURNEY_SESSION_ID=
MIDJOURNEY_QUEUE_MODE=true
MIDJOURNEY_QUEUE_POLL_SECONDS=2
MIDJOURNEY_QUEUE_EXIT_SECONDS=10
GOOGLE_SHEET_URL=
GOOGLE_SHEET_TAB=
GOOGLE_SHEET_CREDENTIALS=
GOOGLE_SHEET_READY_VALUE=
```

Midjourney image generation uses `IMAGE_ENGINE=midjourney` and requires either Discord credentials
(`DISCORD_EMAIL`, `DISCORD_PASSWORD`) or a valid cookies/storage state file.

For multilingual sources (for example Polish pins/tabs like `Gotujka.pl`), leave
`ACCEPT_LANGUAGE` / `PIN_ACCEPT_LANGUAGE` empty to avoid forcing English, or set them
explicitly (example: `pl-PL,pl;q=0.9,en;q=0.8`).

Output text language is resolved per worksheet tab:
- Default: `DEFAULT_OUTPUT_LANGUAGE=en`
- Per-site override: `SITE_LANGUAGE_MAP` or `SITE_LANGUAGE_MAP_FILE` JSON map (example: `{"gotujka.pl":"pl"}`)
- Manual override for a run: `OUTPUT_LANGUAGE` or `--output-language`

Automatic model fallback (optional):
- Set `PRIMARY_MODEL_NAME` (example: `gpt-5-mini`)
- Set `FALLBACK_MODEL_NAME` (example: `gpt-5.2`)
- Enable with `ENABLE_MODEL_FALLBACK=true`
- Fallback triggers when quality gates fail (`MODEL_FALLBACK_MIN_RECIPE_CHARS`, `MODEL_FALLBACK_MIN_FAQ_COUNT`)

ImagineAPI image generation uses `IMAGE_ENGINE=imagineapi` and requires a running ImagineAPI
instance plus `IMAGINE_API_URL` and `IMAGINE_API_TOKEN` from your ImagineAPI `.shared.env`.

To run multiple Streamlit instances in parallel without sharing the same browser profile,
set `MIDJOURNEY_SESSION_ID` to a unique value per instance (the UI auto-sets this if unset).

Google Sheets sync (optional) writes each completed row to a worksheet as the batch runs.
Share the sheet with your service account email and provide the JSON key file path.
The Streamlit UI can save the sheet URL and credentials path into `.env` and stores
uploaded credentials in `.secrets/google-service-account.json`.

**Cost Optimization Settings**:
- `GENERATE_IMAGES=false` - Disable image generation (saves ~$0.24-0.32/article)
- `USE_VISION_PROMPTS=false` - Use template prompts instead of Vision API (saves ~$0.21/article)
- `SKIP_METADATA_ENRICHMENT=true` - Skip GPT enrichment, use defaults (saves ~$0.08/article)
- `SKIP_GPT_FAQS=true` - Only use search APIs for FAQs (saves ~$0.10/article)

**With all optimizations enabled**: ~$0.001-0.01 per article (just Serper API costs)

See `COST_OPTIMIZATION.md` for detailed cost breakdown.

## Template CSV (Optional)

Pass `--template` if you want to enforce a custom header. Otherwise the script uses the default prompt-based schema.

## Usage

Single keyword + URL:

```bash
python generate_recipe_batch.py \
  --keyword "Butternut squash soup" \
  --url "https://example.com/recipe" \
  --out out.csv
```

Multiple URLs with the same keyword:
cl
```bash
python generate_recipe_batch.py \
  --keyword "Butternut squash soup" \
  --url "https://example.com/recipe1" \
  --url "https://example.com/recipe2" \
  --out out.csv
```

Batch input CSV mode - supports two formats:

**Format 1** (original): `focus_keyword`, `url`
```bash
python generate_recipe_batch.py --input recipes_to_process.csv --out out.csv
```

**Format 2** (new): `Recipe Name`, `Pinterest URL`, `Recipe URL`
```csv
Recipe Name,Pinterest URL,Recipe URL
Vanilla Bean Sugar Cookie Bars,https://www.pinterest.com/pin/1022880134128482737/,https://www.recipesloop.com/christmas-vanilla-bean-sugar-cookie-bars-with-sprinkles/
Christmas Frosted Gingerbread Cookie Cups,https://www.pinterest.com/pin/1022880134128450582/,https://www.recipesloop.com/christmas-frosted-gingerbread-cookie-cups-recipe/
```

The script will use the Recipe Name as the focus_keyword and Recipe URL as the source URL.

Optional log level:

```bash
python generate_recipe_batch.py --input recipes_to_process.csv --out out.csv --log-level DEBUG
```

## Output

The output CSV follows the template headers exactly when `--template` is provided. Otherwise it uses:

```
['focus_keyword','topic','faq_text','recipe_text','model_name','temperature','target_words','use_multi_call','featured_image_prompt','instructions_process_image_prompt','serving_image_prompt','WPRM_recipecard_image_prompt','featured_image_generated_url','instructions_process_image_generated_url','serving_image_generated_url','WPRM_recipe)card_url']
```

The `recipe_text` field includes the formatted recipe. Image prompts are always generated and included in the prompt columns. If `GENERATE_IMAGES=true`, the generated image URLs are provided in the URL columns. If `GENERATE_IMAGES=false`, the URL columns will be empty (you can generate images manually using the prompts).

## Tests

```bash
pytest
```
# Recipe-Pipeline
# Recipe-Pipeline
