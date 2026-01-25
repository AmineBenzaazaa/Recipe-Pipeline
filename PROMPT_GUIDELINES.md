# Professional Image Prompt Guidelines

## Overview

The image prompts are designed to generate professional, high-quality food photography suitable for recipe blog articles and websites. They follow strict guidelines to ensure consistent, professional results.

## Key Rules Applied to All Prompts

### 1. No Text Overlay
- **Explicitly excluded**: text overlay, watermark, labels, writing
- **Reason**: Clean images suitable for article use without distracting text
- **Implementation**: Added to every prompt as "no text overlay, no watermark, no labels, no writing"

### 2. Professional Quality Standards
- **Magazine quality**: Editorial food photography style
- **Commercial grade**: Restaurant-quality presentation
- **High resolution**: Sharp focus, professional lighting
- **Food styling**: Professional food styling techniques

### 3. Composition Guidelines
- **Clean backgrounds**: White or neutral backgrounds
- **Professional lighting**: Natural, soft lighting
- **Appetizing presentation**: Photogenic, inviting composition
- **Consistent styling**: Same visual style across all images in a batch

### 4. Technical Specifications
- **Quality**: Set to `5` (maximum quality for Midjourney, range: 0.25-5)
- **Aspect ratios**: 
  - Featured: 3:2 (landscape, hero shot)
  - Instructions: 2:3 (portrait, process shot)
  - Serving: 2:3 (portrait, presentation shot)
- **Seed consistency**: Same seed for all images in a batch for visual continuity
- **Platform**: Midjourney-compatible prompts

## Prompt Structure

Each prompt follows this structure:

1. **Subject**: Clear description of the dish
2. **Composition**: Professional styling and presentation details
3. **Quality rules**: Professional photography standards
4. **Style anchor**: Consistent visual style (from config)
5. **Technical params**: Aspect ratio, seed, quality, style

## Example Prompt Breakdown

### Featured Image Prompt
```
Professional food photography of [dish], hero shot of the finished recipe. 
Beautifully styled and plated, showcasing all key ingredients and textures. 
Clean white or neutral background, professional composition, appetizing presentation. 
[Professional rules: no text, high quality, etc.]. 
[Style anchor: soft natural light, etc.]. 
Exact visual consistency for batch reference. 
--ar 3:2 --seed [seed] --quality 5
```

**Key Elements**:
- "Professional food photography" - Sets the quality bar
- "Hero shot" - Indicates primary article image
- "No text overlay" - Explicit exclusion
- "--quality 5" - Maximum quality for Midjourney (0.25-5 range)
- Midjourney-compatible parameters

## Image Types

### 1. Featured Image (Hero Shot)
- **Purpose**: Main article image, first impression
- **Aspect Ratio**: 3:2 (landscape)
- **Style**: Hero shot, finished dish, all details visible
- **Use**: Top of article, social media sharing

### 2. Instructions Process Image
- **Purpose**: Show cooking process, techniques
- **Aspect Ratio**: 2:3 (portrait)
- **Style**: Action shot, hands working, ingredients visible
- **Use**: Within recipe instructions section

### 3. Serving Image
- **Purpose**: Final presentation, serving suggestion
- **Aspect Ratio**: 2:3 (portrait)
- **Style**: Elegantly plated, restaurant-quality presentation
- **Use**: Before serving section, recipe card

## Quality Assurance

### Automatic Quality Enforcement
- Quality set to maximum (5) for Midjourney
- Ensures highest quality output for professional articles
- Midjourney-compatible parameters throughout

### Consistency Rules
- Same seed ensures visual consistency across batch
- Same style anchor maintains cohesive look
- "Same batch" references ensure continuity

## Customization

### Style Anchor
Configure in `.env`:
```bash
STYLE_ANCHOR=soft natural light, shallow depth of field, editorial food photography, high detail, 85mm lens, professional food styling, appetizing, restaurant quality, magazine style, commercial photography
```

### Image Quality
Configure in `.env`:
```bash
IMAGE_QUALITY=high  # Options: high, hd, standard
```

### Image Model
Configure in `.env`:
```bash
IMAGE_MODEL=gpt-image-1.5  # or your preferred model
```

## Best Practices

1. **Always use high quality** - Professional articles need professional images
2. **Maintain consistency** - Same seed and style across all images
3. **No text overlays** - Keep images clean for article use
4. **Professional styling** - Restaurant-quality presentation
5. **Appetizing composition** - Make food look inviting and photogenic

## Troubleshooting

### If images have text overlays:
- Check that prompts include "no text overlay, no watermark, no labels"
- Verify the prompt is being used correctly
- Try regenerating with explicit negative prompts

### If quality is low:
- Verify `--quality 5` is in the prompt (Midjourney maximum)
- Check Midjourney version supports quality parameter
- Ensure prompts are being used correctly in Midjourney

### If images are inconsistent:
- Ensure same seed is used for all images in batch
- Check that style anchor is consistent
- Verify "same batch" references in prompts

## Output Specifications

All generated images will have:
- ✅ No text overlays
- ✅ High quality resolution
- ✅ Professional food styling
- ✅ Consistent visual style
- ✅ Appetizing presentation
- ✅ Clean composition
- ✅ Magazine-quality photography

These images are ready for use in professional recipe blog articles.

