# Recipe Pipeline Batch Generator

Production-ready script to extract recipe data, FAQs, and image prompts into a CSV row per recipe.

## Setup

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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
SLEEP_SECONDS=1
IMAGE_MODEL=gpt-image-1
IMAGE_QUALITY=high
GENERATE_IMAGES=false
USE_VISION_PROMPTS=false
SKIP_METADATA_ENRICHMENT=true
SKIP_GPT_FAQS=true
IMAGE_OUTPUT_DIR=generated_images
CLOUDINARY_URL=cloudinary://api_key:api_secret@cloud_name
CLOUDINARY_UPLOAD_PRESET=
CLOUDINARY_FOLDER=recipe-pipeline
```

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
