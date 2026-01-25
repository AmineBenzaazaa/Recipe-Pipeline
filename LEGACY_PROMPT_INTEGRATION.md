# Legacy Prompt Generation Integration

## Overview

I've integrated the proven prompt generation approach from `legacy.py` into the Recipe Pipeline system. The legacy approach uses GPT to analyze recipe content and generate customized, context-aware prompts.

## Key Differences: Legacy vs Current

### Legacy Approach (Now Integrated) ✅
- **Uses GPT** to analyze recipe content and generate customized prompts
- **Simpler, cleaner prompts**: "Photo-realistic food photography of [dish name], hero shot..."
- **Simple style anchor**: "Exact same batch as the featured image. focus on the recipe."
- **Context-aware**: Prompts are customized based on actual recipe content
- **Proven to work**: This is the approach that's been working in your legacy system

### Old Current Approach (Replaced)
- Template-based static prompts
- Overly complex with many rules
- Less context-aware

## New Implementation

### 1. New Module: `src/midjourney_prompts.py`
- `generate_midjourney_prompts_gpt()` - GPT-based prompt generation (legacy approach)
- `generate_template_prompts()` - Fallback template prompts (legacy-style simple format)

### 2. Updated Prompt Flow
The system now follows this priority:
1. **GPT-based generation** (if OpenAI key available and vision disabled) - **Preferred**
2. **Vision-based generation** (if vision enabled and images available)
3. **Template prompts** (fallback - legacy-style simple format)

### 3. Legacy-Style Prompts
All prompts now follow the legacy format:
```
Photo-realistic food photography of [dish name], hero shot of the finished recipe with all key details visible. Exact batch reference for later steps. Exact same batch as the featured image. focus on the recipe. no text no words no letters no typography no watermark no logo no branding no labels --ar 3:2 --seed [seed] --quality 5
```

## Key Features from Legacy

### 1. GPT Analysis
- Analyzes recipe content (first 3000 chars)
- Customizes prompts based on actual dish details
- Replaces `[dish name]` with actual recipe name
- Makes prompts specific to the recipe

### 2. Simple Style Anchor
- Changed from complex style description to: "Exact same batch as the featured image. focus on the recipe."
- This is what worked in legacy.py

### 3. Cleaner Prompts
- Removed overly complex professional rules
- Focused on essential elements
- Simpler structure that Midjourney understands better

### 4. Proper Text Exclusions
- Added "no text no words..." before `--ar` parameter
- Uses plain text (not `--no` parameters)
- Placed correctly in prompt structure

## Configuration

### Default Behavior
- **GPT-based prompts enabled by default** (if OpenAI key is set)
- Uses legacy approach automatically
- Falls back to templates if GPT fails

### To Use GPT Prompts
```bash
# In .env
OPENAI_API_KEY=your_key
USE_VISION_PROMPTS=false  # Disable vision (GPT is cheaper and better)
```

### To Use Template Prompts Only
```bash
# In .env
OPENAI_API_KEY=  # Leave empty
# Or set USE_VISION_PROMPTS=false
```

## Prompt Structure (Legacy Style)

### Featured Image
```
Photo-realistic food photography of [actual dish name], hero shot of the finished recipe with all key details visible. Exact batch reference for later steps. Exact same batch as the featured image. focus on the recipe. no text no words no letters no typography no watermark no logo no branding no labels --ar 3:2 --seed [seed] --quality 5
```

### Instructions Process
```
Instructions-only process photo of [actual dish name] preparation, hands working with ingredients and cooking techniques. Same batch as featured image, vertical composition showing cooking process. Exact same batch as the featured image. focus on the recipe. no text no words no letters no typography no watermark no logo no branding no labels --ar 2:3 --seed [seed] --quality 5
```

### Serving
```
Elegant serving presentation of [actual dish name], beautifully plated and ready to serve. Same batch as featured image, showing the dish in its final serving context. Exact same batch as the featured image. focus on the recipe. no text no words no letters no typography no watermark no logo no branding no labels --ar 2:3 --seed [seed] --quality 5
```

## Benefits

1. **Proven Approach**: Uses the same method that works in your legacy system
2. **Context-Aware**: GPT customizes prompts based on actual recipe
3. **Simpler Prompts**: Cleaner structure that Midjourney understands
4. **Better Results**: Should produce better images with less text overlays
5. **Cost Effective**: GPT prompt generation is cheaper than Vision API

## Files Changed

1. **src/midjourney_prompts.py** - New module with legacy approach
2. **generate_recipe_batch.py** - Updated to use GPT prompts first
3. **src/config.py** - Updated style anchor to legacy format
4. **src/formatters.py** - Still available as fallback

## Testing

Regenerate your CSV to get the new GPT-generated prompts:
```bash
python generate_recipe_batch.py --input test_input.csv --out test_output.csv
```

The prompts will now be:
- Generated by GPT based on recipe content
- Customized to the actual dish
- Following the proven legacy format
- With proper text exclusions

## Expected Results

- ✅ Prompts customized to actual recipe
- ✅ Simpler, cleaner structure
- ✅ Better Midjourney compatibility
- ✅ Less text overlays (proper exclusions)
- ✅ Consistent style across batch

