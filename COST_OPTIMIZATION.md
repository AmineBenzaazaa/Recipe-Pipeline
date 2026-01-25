# Cost Optimization Guide

## Current API Costs Breakdown

Even with image generation disabled, you're still paying for:

| Service | Cost | When Used |
|---------|------|-----------|
| **Vision API** | ~$0.21 | Analyzing recipe images to generate enhanced prompts |
| **GPT Enrichment** | ~$0.08 | Filling missing metadata (prep time, calories, etc.) |
| **GPT FAQs** | ~$0.10 | Generating FAQs if search APIs don't return enough |
| **GPT Extraction** | ~$0.14 | Fallback if JSON-LD extraction fails |
| **Serper API** | ~$0.001 | FAQ search (very cheap) |

**Total without optimizations**: ~$0.40-0.50 per article

## New Cost-Saving Options

I've added three new environment variables to disable expensive features:

### 1. Disable Vision Prompts (Save ~$0.21)
```bash
USE_VISION_PROMPTS=false
```
- **Default**: `false` (disabled)
- **What it does**: Uses template prompts instead of Vision API analysis
- **Savings**: ~$0.21 per article
- **Trade-off**: Prompts are slightly less customized but still good quality

### 2. Skip Metadata Enrichment (Save ~$0.08)
```bash
SKIP_METADATA_ENRICHMENT=true
```
- **Default**: `false` (enabled)
- **What it does**: Uses defaults for missing metadata instead of GPT enrichment
- **Savings**: ~$0.08 per article
- **Trade-off**: May have less accurate prep time, calories, etc.

### 3. Skip GPT FAQs (Save ~$0.10)
```bash
SKIP_GPT_FAQS=true
```
- **Default**: `false` (enabled)
- **What it does**: Only uses Serper/SerpAPI for FAQs, no GPT fallback
- **Savings**: ~$0.10 per article
- **Trade-off**: May have fewer FAQs if search APIs don't return enough

## Recommended Low-Cost Configuration

For maximum cost savings, use this `.env` configuration:

```bash
# Disable all expensive features
GENERATE_IMAGES=false
USE_VISION_PROMPTS=false
SKIP_METADATA_ENRICHMENT=true
SKIP_GPT_FAQS=true

# Keep these enabled (they're cheap or free)
# SERPER_API_KEY=your_key (for FAQs - very cheap)
```

**Cost with this config**: ~$0.001-0.01 per article (just Serper API for FAQs)

## Cost Comparison

| Configuration | Cost Per Article |
|---------------|------------------|
| **Full features** (all enabled) | ~$0.50-0.72 |
| **No image generation** | ~$0.40-0.50 |
| **No vision prompts** | ~$0.19-0.29 |
| **Skip enrichment** | ~$0.11-0.21 |
| **Skip GPT FAQs** | ~$0.01-0.11 |
| **Minimal (recommended)** | ~$0.001-0.01 |

## What You Still Get

Even with all optimizations enabled, you still get:
- ✅ Recipe extraction from HTML/JSON-LD
- ✅ Formatted recipe text
- ✅ Image prompts (template-based, still good quality)
- ✅ FAQs from search APIs (if configured)
- ✅ All CSV columns populated (except image URLs)

## Usage

1. **Update your `.env` file**:
```bash
GENERATE_IMAGES=false
USE_VISION_PROMPTS=false
SKIP_METADATA_ENRICHMENT=true
SKIP_GPT_FAQS=true
```

2. **Run as normal**:
```bash
python generate_recipe_batch.py --input sample_input.csv --out output.csv
```

3. **Check the logs** - you'll see messages like:
   - "Vision prompts disabled - using template prompts"
   - "Metadata enrichment skipped - using defaults"
   - "GPT FAQ generation skipped"

## Gradual Optimization

You can enable features one at a time to find the right balance:

1. **Start minimal**: All optimizations enabled (~$0.01/article)
2. **Add GPT FAQs**: Set `SKIP_GPT_FAQS=false` (~$0.11/article)
3. **Add enrichment**: Set `SKIP_METADATA_ENRICHMENT=false` (~$0.19/article)
4. **Add vision prompts**: Set `USE_VISION_PROMPTS=true` (~$0.40/article)
5. **Add image generation**: Set `GENERATE_IMAGES=true` (~$0.72/article)

