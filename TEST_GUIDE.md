# Test Guide - Recipe Pipeline

## Test Data Ready

I've created `test_input.csv` with your 3 recipes:

1. Vanilla Bean Sugar Cookie Bars
2. Christmas Frosted Gingerbread Cookie Cups  
3. Toasted Almond Snowball Cookies

## How to Run the Test

### 1. Activate Virtual Environment
```bash
cd /Users/useraccount/Documents/Blogging/RecipePipeline
source .venv/bin/activate  # or python3 -m venv .venv if needed
```

### 2. Ensure Environment Variables are Set
Make sure your `.env` file has the cost-optimized settings:
```bash
GENERATE_IMAGES=false
USE_VISION_PROMPTS=false
SKIP_METADATA_ENRICHMENT=true
SKIP_GPT_FAQS=true
```

### 3. Run the Pipeline
```bash
python generate_recipe_batch.py --input test_input.csv --out test_output.csv --log-level INFO
```

### 4. Check the Output
```bash
# View the output CSV
cat test_output.csv

# Or open in Excel/Numbers
open test_output.csv
```

## What to Expect

The output CSV will contain:
- ✅ Recipe data (name, ingredients, instructions)
- ✅ Formatted recipe text
- ✅ **Professional image prompts** (3 per recipe)
- ✅ FAQ text (from search APIs)
- ❌ Image URLs (empty, since generation is disabled)

## Expected Prompts

Each recipe will have 3 professional prompts:

1. **Featured Image Prompt** (hero shot)
   - Professional food photography
   - No text overlay
   - High quality specifications
   - 3:2 aspect ratio

2. **Instructions Process Prompt** (cooking process)
   - Professional process photography
   - Action shots with ingredients
   - 2:3 aspect ratio

3. **Serving Prompt** (final presentation)
   - Elegant plating
   - Restaurant-quality presentation
   - 2:3 aspect ratio

## Cost Estimate

With the optimized settings:
- **Per recipe**: ~$0.001-0.01
- **Total for 3 recipes**: ~$0.003-0.03
- **Main cost**: Serper API for FAQs (very cheap)

## Troubleshooting

### If you get permission errors:
- Make sure you're using the virtual environment
- Check file permissions: `chmod +x generate_recipe_batch.py`

### If recipes fail to extract:
- Check the URLs are accessible
- Review logs for specific errors
- Some sites may block automated access

### If prompts are missing:
- Check that the recipe extraction succeeded
- Verify OpenAI API key is set (even if not using expensive features)
- Review logs for warnings

## Next Steps After Testing

1. **Review the prompts** - Check quality and professionalism
2. **Verify no text overlays** - Prompts should explicitly exclude text
3. **Check consistency** - Same seed ensures visual consistency
4. **Generate images** (when ready) - Use the prompts manually or enable generation

## Sample Output Structure

```csv
focus_keyword,topic,featured_image_prompt,instructions_process_image_prompt,serving_image_prompt,...
Vanilla Bean Sugar Cookie Bars,Vanilla Bean Sugar Cookie Bars,"Professional food photography of Vanilla Bean Sugar Cookie Bars...","Professional food photography of Vanilla Bean Sugar Cookie Bars preparation...","Professional food photography of Vanilla Bean Sugar Cookie Bars...",...
```

Each prompt will be a complete, professional description ready for image generation.

