# API Cost Analysis - Per Article

This document breaks down the API costs for generating one complete article with 3 images.

## API Calls Per Article

Based on the codebase analysis, here's what happens when processing one recipe article:

### 1. Recipe Extraction (Conditional - GPT Fallback)
**When**: Only if JSON-LD and HTML fallback extraction fail or produce incomplete results
- **API**: OpenAI GPT (model: `gpt-4.1` by default)
- **Endpoint**: `/v1/responses`
- **Tokens**: ~800 output tokens
- **Input**: ~12,000 characters (truncated HTML)
- **Cost**: ~$0.01-0.03 (if needed)

### 2. Recipe Metadata Enrichment (Conditional)
**When**: Only if required fields (prep_time, cook_time, servings, calories, cuisine, course) are missing
- **API**: OpenAI GPT (model: `gpt-4.1` by default)
- **Endpoint**: `/v1/responses`
- **Tokens**: ~400 output tokens
- **Input**: Recipe context + search results (if available)
- **Cost**: ~$0.005-0.015 (if needed)
- **Note**: May also use Serper/SerpAPI for search context (optional, separate cost)

### 3. Image Prompt Generation (Conditional)
**When**: If images are available from the recipe page and OpenAI key is configured
- **API**: OpenAI Vision (model: `gpt-4.1` by default)
- **Endpoint**: `/v1/responses`
- **Tokens**: ~1,200 output tokens
- **Input**: 2 images (base64 encoded) + recipe context + template
- **Cost**: ~$0.01-0.04 (if images available)
- **Note**: Falls back to template prompts if no images or API fails

### 4. FAQ Generation (Conditional)
**When**: If Serper/SerpAPI don't return enough FAQs (< 6 items)
- **API**: OpenAI GPT (model: `gpt-4.1` by default)
- **Endpoint**: `/v1/responses`
- **Tokens**: ~900 output tokens
- **Input**: Recipe context + focus keyword
- **Cost**: ~$0.01-0.03 (if needed)
- **Note**: First tries Serper API ($0.001-0.01 per search) or SerpAPI ($0.002-0.05 per search)

### 5. Image Generation (Required - 3 Images)
**When**: Always (if `GENERATE_IMAGES=true`)
- **API**: OpenAI DALL-E (model: `gpt-image-1.5` by default)
- **Endpoint**: `/v1/images/generations`
- **Images**: 3 images (featured, instructions_process, serving)
- **Sizes**: 
  - Featured: 1536x1024 (3:2 aspect ratio)
  - Instructions: 1024x1536 (2:3 aspect ratio)
  - Serving: 1024x1536 (2:3 aspect ratio)
- **Quality**: High (default)
- **Cost**: **$0.24-0.30** (this is the main cost)

## Cost Breakdown

### Scenario 1: Best Case (Minimal API Usage)
**Assumptions**:
- Recipe has good JSON-LD data (no GPT extraction needed)
- Recipe has complete metadata (no enrichment needed)
- Recipe has images (vision prompt generation used)
- Serper API returns enough FAQs (no GPT FAQ needed)
- 3 images generated

| Service | Calls | Cost |
|---------|-------|------|
| OpenAI Vision (prompts) | 1 | $0.01-0.04 |
| OpenAI DALL-E (images) | 3 | $0.24-0.30 |
| Serper API (FAQs) | 1 | $0.001-0.01 |
| **Total** | | **$0.25-0.35** |

### Scenario 2: Worst Case (Maximum API Usage)
**Assumptions**:
- Recipe needs GPT extraction
- Recipe needs metadata enrichment
- Recipe has images (vision prompt generation)
- Serper fails, GPT FAQ generation needed
- 3 images generated

| Service | Calls | Cost |
|---------|-------|------|
| OpenAI GPT (extraction) | 1 | $0.01-0.03 |
| OpenAI GPT (enrichment) | 1 | $0.005-0.015 |
| OpenAI Vision (prompts) | 1 | $0.01-0.04 |
| OpenAI GPT (FAQs) | 1 | $0.01-0.03 |
| OpenAI DALL-E (images) | 3 | $0.24-0.30 |
| Serper API (FAQs - failed) | 1 | $0.001-0.01 |
| **Total** | | **$0.28-0.42** |

### Scenario 3: Typical Case (Average Usage)
**Assumptions**:
- Recipe has partial data (needs some enrichment)
- Recipe has images (vision prompt generation)
- Serper returns some FAQs, GPT supplements
- 3 images generated

| Service | Calls | Cost |
|---------|-------|------|
| OpenAI GPT (enrichment) | 1 | $0.005-0.015 |
| OpenAI Vision (prompts) | 1 | $0.01-0.04 |
| OpenAI GPT (FAQs - partial) | 1 | $0.01-0.03 |
| OpenAI DALL-E (images) | 3 | $0.24-0.30 |
| Serper API (FAQs) | 1 | $0.001-0.01 |
| **Total** | | **$0.28-0.40** |

## Cost Per Article: **$0.25 - $0.42**

**Most likely cost: ~$0.30-0.35 per article**

## Cost Breakdown by Component

### Image Generation (Main Cost)
- **3 images × $0.08-0.10 per image = $0.24-0.30**
- This is **80-85%** of total cost
- Quality: High (default)
- Sizes: 1024x1024, 1536x1024, or 1024x1536

### Text Generation (Secondary Cost)
- **$0.02-0.10** total for all GPT calls
- Includes: extraction, enrichment, prompts, FAQs
- This is **10-20%** of total cost

### Search APIs (Minimal Cost)
- **Serper API**: $0.001-0.01 per search
- **SerpAPI**: $0.002-0.05 per search (if used)
- This is **<5%** of total cost

## Cost Optimization Strategies

### 1. Reduce Image Generation Costs
- **Option A**: Use "standard" quality instead of "high" (saves ~20%)
  - High: $0.08-0.10/image
  - Standard: $0.06-0.08/image
  - **Savings**: ~$0.06-0.09 per article

- **Option B**: Generate fewer images (2 instead of 3)
  - **Savings**: ~$0.08-0.10 per article

- **Option C**: Use smaller image sizes
  - 1024x1024 is cheaper than 1536x1024
  - **Savings**: ~$0.02-0.03 per article

### 2. Optimize Text Generation
- **Option A**: Skip GPT extraction if possible (ensure good JSON-LD)
  - **Savings**: ~$0.01-0.03 per article

- **Option B**: Skip metadata enrichment (ensure complete recipe data)
  - **Savings**: ~$0.005-0.015 per article

- **Option C**: Use cheaper model for non-critical tasks
  - GPT-4.1 → GPT-3.5-turbo (if available)
  - **Savings**: ~50% on text generation (~$0.01-0.05 per article)

### 3. Optimize FAQ Generation
- **Option A**: Always use Serper/SerpAPI first (cheaper than GPT)
  - **Savings**: ~$0.01-0.03 per article

- **Option B**: Accept fewer FAQs (reduce GPT fallback threshold)
  - **Savings**: ~$0.01-0.03 per article

## Monthly Cost Estimates

### Publishing Frequency

| Articles/Month | Cost/Month (Best) | Cost/Month (Typical) | Cost/Month (Worst) |
|----------------|-------------------|----------------------|-------------------|
| 10 articles | $2.50-3.50 | $2.80-4.00 | $2.80-4.20 |
| 50 articles | $12.50-17.50 | $14.00-20.00 | $14.00-21.00 |
| 100 articles | $25.00-35.00 | $28.00-40.00 | $28.00-42.00 |
| 200 articles | $50.00-70.00 | $56.00-80.00 | $56.00-84.00 |
| 500 articles | $125.00-175.00 | $140.00-200.00 | $140.00-210.00 |

## API Pricing Reference (as of 2024)

### OpenAI Pricing
- **GPT-4.1 (Responses API)**: ~$0.01-0.03 per 1K tokens (input/output)
- **DALL-E 3 (Images)**:
  - Standard quality: $0.04/image (1024×1024), $0.08/image (1024×1792 or 1792×1024)
  - HD quality: $0.08/image (1024×1024), $0.12/image (1024×1792 or 1792×1024)
- **Vision API**: Similar to GPT-4 pricing

### Serper API Pricing
- **Free tier**: 2,500 searches/month
- **Paid**: $5/month for 5,000 searches ($0.001/search)

### SerpAPI Pricing
- **Free tier**: 100 searches/month
- **Paid**: $50/month for 5,000 searches ($0.01/search)

## Recommendations

1. **For Cost-Conscious Publishing**:
   - Use "standard" image quality
   - Ensure recipes have good JSON-LD data
   - Use Serper API for FAQs (cheaper)
   - **Target cost**: ~$0.20-0.25 per article

2. **For Quality-Focused Publishing**:
   - Use "high" image quality
   - Allow GPT enrichment for better metadata
   - Generate all 3 images
   - **Target cost**: ~$0.30-0.35 per article

3. **For High-Volume Publishing**:
   - Consider OpenAI volume discounts
   - Cache image prompts when possible
   - Batch process articles
   - **Target cost**: ~$0.25-0.30 per article (with optimizations)

## Notes

- Costs are estimates based on typical usage patterns
- Actual costs may vary based on:
  - Token usage (varies by recipe complexity)
  - Image generation success rate
  - API rate limits and retries
  - Regional pricing differences
- The codebase includes retry logic which may increase costs slightly on failures
- Cloudinary uploads (if configured) are separate and typically free for reasonable usage

