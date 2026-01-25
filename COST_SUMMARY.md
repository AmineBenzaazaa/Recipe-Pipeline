# Cost Summary - Per Article

## Quick Answer

**Cost per article with 3 images: $0.25 - $0.72**

**Most likely cost: ~$0.30-0.40 per article**

## Detailed Breakdown

### Main Cost Component: Image Generation
- **3 images × $0.08-0.12 per image = $0.24-0.36**
- This represents **70-85%** of total costs
- Quality: High (default)
- Sizes: Mixed (1024×1024, 1536×1024, 1024×1536)

### Secondary Costs: Text Generation
- **$0.05-0.30** for all GPT calls combined
- Includes: metadata enrichment, vision prompts, FAQ generation
- This represents **15-30%** of total costs

### Minimal Costs: Search APIs
- **Serper API**: $0.001 per search
- **SerpAPI**: $0.01 per search (if used)
- This represents **<1%** of total costs

## Cost Scenarios

### Best Case: ~$0.25-0.30
- Good recipe data (no GPT extraction needed)
- Complete metadata (no enrichment needed)
- Images available (vision prompts used)
- Serper returns FAQs (no GPT FAQ needed)
- 3 high-quality images

### Typical Case: ~$0.30-0.40
- Partial recipe data (needs some enrichment)
- Images available (vision prompts used)
- Serper + GPT for FAQs
- 3 high-quality images

### Worst Case: ~$0.50-0.72
- Poor recipe data (needs GPT extraction)
- Missing metadata (needs enrichment)
- Images available (vision prompts used)
- GPT FAQ generation needed
- 3 high-quality images

## Cost Optimization

### Quick Wins (Save 20-30%)
1. **Use "standard" image quality** → Save ~$0.06-0.09 per article
2. **Generate 2 images instead of 3** → Save ~$0.08-0.12 per article
3. **Ensure good recipe data** → Save ~$0.01-0.03 per article

### Advanced Optimizations
1. **Batch processing** → May qualify for volume discounts
2. **Cache image prompts** → Reuse prompts for similar recipes
3. **Use cheaper models** → GPT-3.5 for non-critical tasks (if available)

## Monthly Cost Estimates

| Articles/Month | Cost Range |
|----------------|------------|
| 10 | $2.50 - $7.20 |
| 50 | $12.50 - $36.00 |
| 100 | $25.00 - $72.00 |
| 200 | $50.00 - $144.00 |
| 500 | $125.00 - $360.00 |

**Recommended budget**: Plan for ~$0.35 per article on average.

## Usage

Run the cost calculator:
```bash
python3 calculate_costs.py --scenario typical
python3 calculate_costs.py --articles 100 --scenario typical
python3 calculate_costs.py --image-quality standard --num-images 2
```

See `API_COST_ANALYSIS.md` for detailed breakdown and `calculate_costs.py` for the calculator script.

