# Image Generation Disabled - Prompts Only Mode

## Changes Made

### 1. Image Generation Disabled by Default
- **Setting**: `GENERATE_IMAGES=false` (default)
- **Behavior**: Image prompts are still generated, but actual image generation is skipped
- **Cost Savings**: ~$0.24-0.32 per article (image generation costs)

### 2. CSV Input Format Support
The script now supports two CSV input formats:

#### Format 1 (Original)
```csv
focus_keyword,url
Vanilla Bean Sugar Cookie Bars,https://www.recipesloop.com/recipe/
```

#### Format 2 (New - Your Format)
```csv
Recipe Name,Pinterest URL,Recipe URL
Vanilla Bean Sugar Cookie Bars,https://www.pinterest.com/pin/123/,https://www.recipesloop.com/recipe/
```

The script automatically detects which format you're using.

### 3. Output CSV Structure
The output CSV still includes all columns:
- **Prompt columns** (always populated):
  - `featured_image_prompt`
  - `instructions_process_image_prompt`
  - `serving_image_prompt`
  - `WPRM_recipecard_image_prompt`

- **URL columns** (empty when `GENERATE_IMAGES=false`):
  - `featured_image_generated_url`
  - `instructions_process_image_generated_url`
  - `serving_image_generated_url`
  - `WPRM_recipe)card_url`

You can manually generate images using the prompts later.

## Usage

### 1. Set Environment Variable
In your `.env` file:
```bash
GENERATE_IMAGES=false
```

Or leave it unset (defaults to `false` now).

### 2. Prepare Your Input CSV
Create a CSV file with your recipe data:

```csv
Recipe Name,Pinterest URL,Recipe URL
Vanilla Bean Sugar Cookie Bars,https://www.pinterest.com/pin/1022880134128482737/,https://www.recipesloop.com/christmas-vanilla-bean-sugar-cookie-bars-with-sprinkles/
Christmas Frosted Gingerbread Cookie Cups,https://www.pinterest.com/pin/1022880134128450582/,https://www.recipesloop.com/christmas-frosted-gingerbread-cookie-cups-recipe/
Toasted Almond Snowball Cookies,https://www.pinterest.com/pin/1022880134128442796/,https://www.recipesloop.com/christmas-rainbow-holiday-cupcakes-with-sprinkles/
```

### 3. Run the Script
```bash
python generate_recipe_batch.py --input sample_input.csv --out output.csv
```

### 4. Use the Prompts Manually
The output CSV will contain all the image prompts. You can:
- Copy the prompts to your image generation tool
- Generate images manually
- Add the image URLs back to the CSV later

## Cost Comparison

### With Image Generation Enabled
- **Per Article**: ~$0.50-0.72
- **Main Cost**: Image generation ($0.24-0.32)

### With Image Generation Disabled (Current)
- **Per Article**: ~$0.20-0.40
- **Main Cost**: Text generation only (enrichment, prompts, FAQs)
- **Savings**: ~$0.24-0.32 per article

## Re-enabling Image Generation

If you want to generate images again later, simply set:
```bash
GENERATE_IMAGES=true
```

The script will then generate both prompts AND images.

## Example Output

When `GENERATE_IMAGES=false`, your output CSV will look like:

```csv
focus_keyword,topic,featured_image_prompt,featured_image_generated_url,...
Vanilla Bean Sugar Cookie Bars,Vanilla Bean Sugar Cookie Bars,"Photo-realistic food photography of Vanilla Bean Sugar Cookie Bars...","",...
```

Notice:
- ✅ `featured_image_prompt` is populated
- ❌ `featured_image_generated_url` is empty

## Benefits

1. **Cost Savings**: Save ~$0.24-0.32 per article
2. **Flexibility**: Generate images manually when ready
3. **Quality Control**: Review prompts before generating images
4. **Batch Processing**: Process many recipes quickly, generate images later

