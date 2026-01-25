#!/usr/bin/env python3
"""
Cost Calculator for Recipe Pipeline Articles

This script calculates the estimated API costs for generating recipe articles.
"""

import argparse
from typing import Dict, Optional


# OpenAI API Pricing (as of 2024, estimates)
PRICING = {
    "gpt4_input": 0.03,  # per 1K tokens
    "gpt4_output": 0.06,  # per 1K tokens
    "gpt4_vision_input": 0.01,  # per image
    "dalle3_standard_1024": 0.04,  # per image
    "dalle3_standard_1792": 0.08,  # per image
    "dalle3_hd_1024": 0.08,  # per image
    "dalle3_hd_1792": 0.12,  # per image
    "serper_search": 0.001,  # per search
    "serpapi_search": 0.01,  # per search
}

# Typical token usage per call
TOKEN_USAGE = {
    "extraction": {"input": 3000, "output": 800},
    "enrichment": {"input": 2000, "output": 400},
    "vision_prompts": {"input": 4000, "output": 1200, "images": 2},
    "faqs": {"input": 1500, "output": 900},
}


def calculate_gpt_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = "gpt4"
) -> float:
    """Calculate GPT API cost."""
    input_cost = (input_tokens / 1000) * PRICING[f"{model}_input"]
    output_cost = (output_tokens / 1000) * PRICING[f"{model}_output"]
    return input_cost + output_cost


def calculate_vision_cost(
    input_tokens: int,
    output_tokens: int,
    num_images: int,
    model: str = "gpt4"
) -> float:
    """Calculate Vision API cost."""
    text_cost = calculate_gpt_cost(input_tokens, output_tokens, model)
    image_cost = num_images * PRICING[f"{model}_vision_input"]
    return text_cost + image_cost


def calculate_image_cost(
    num_images: int,
    quality: str = "high",
    size: str = "1024x1024"
) -> float:
    """Calculate DALL-E image generation cost."""
    if quality == "standard":
        if size == "1024x1024":
            return num_images * PRICING["dalle3_standard_1024"]
        else:
            return num_images * PRICING["dalle3_standard_1792"]
    else:  # high/hd
        if size == "1024x1024":
            return num_images * PRICING["dalle3_hd_1024"]
        else:
            return num_images * PRICING["dalle3_hd_1792"]


def calculate_article_cost(
    use_gpt_extraction: bool = False,
    use_metadata_enrichment: bool = True,
    use_vision_prompts: bool = True,
    use_gpt_faqs: bool = False,
    use_serper: bool = True,
    num_images: int = 3,
    image_quality: str = "high",
    image_sizes: Optional[list] = None
) -> Dict[str, float]:
    """
    Calculate total cost for one article.
    
    Args:
        use_gpt_extraction: Whether GPT extraction is needed
        use_metadata_enrichment: Whether metadata enrichment is needed
        use_vision_prompts: Whether vision-based prompt generation is used
        use_gpt_faqs: Whether GPT FAQ generation is needed
        use_serper: Whether Serper API is used for FAQs
        num_images: Number of images to generate
        image_quality: Image quality (standard or high)
        image_sizes: List of image sizes (defaults to [1024x1024, 1536x1024, 1024x1536])
    
    Returns:
        Dictionary with cost breakdown
    """
    if image_sizes is None:
        image_sizes = ["1024x1024", "1536x1024", "1024x1536"]
    
    costs = {
        "extraction": 0.0,
        "enrichment": 0.0,
        "vision_prompts": 0.0,
        "faqs_gpt": 0.0,
        "faqs_search": 0.0,
        "images": 0.0,
    }
    
    # GPT Extraction (if needed)
    if use_gpt_extraction:
        usage = TOKEN_USAGE["extraction"]
        costs["extraction"] = calculate_gpt_cost(
            usage["input"], usage["output"]
        )
    
    # Metadata Enrichment (if needed)
    if use_metadata_enrichment:
        usage = TOKEN_USAGE["enrichment"]
        costs["enrichment"] = calculate_gpt_cost(
            usage["input"], usage["output"]
        )
    
    # Vision Prompts (if images available)
    if use_vision_prompts:
        usage = TOKEN_USAGE["vision_prompts"]
        costs["vision_prompts"] = calculate_vision_cost(
            usage["input"], usage["output"], usage["images"]
        )
    
    # FAQ Generation
    if use_serper:
        costs["faqs_search"] = PRICING["serper_search"]
    
    if use_gpt_faqs:
        usage = TOKEN_USAGE["faqs"]
        costs["faqs_gpt"] = calculate_gpt_cost(
            usage["input"], usage["output"]
        )
    
    # Image Generation (main cost)
    for i, size in enumerate(image_sizes[:num_images]):
        if "1792" in size or "1536" in size:
            size_key = "1792"
        else:
            size_key = "1024"
        costs["images"] += calculate_image_cost(1, image_quality, f"{size_key}x{size_key}")
    
    total = sum(costs.values())
    costs["total"] = total
    
    return costs


def print_cost_breakdown(costs: Dict[str, float], scenario: str = ""):
    """Print formatted cost breakdown."""
    if scenario:
        print(f"\n{scenario}")
        print("=" * 60)
    
    print("\nCost Breakdown:")
    print("-" * 60)
    print(f"  GPT Extraction:        ${costs['extraction']:.4f}")
    print(f"  Metadata Enrichment:   ${costs['enrichment']:.4f}")
    print(f"  Vision Prompts:        ${costs['vision_prompts']:.4f}")
    print(f"  FAQ Search (Serper):   ${costs['faqs_search']:.4f}")
    print(f"  FAQ Generation (GPT):  ${costs['faqs_gpt']:.4f}")
    print(f"  Image Generation:      ${costs['images']:.4f}")
    print("-" * 60)
    print(f"  TOTAL:                 ${costs['total']:.4f}")
    print(f"  TOTAL (rounded):       ${costs['total']:.2f}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Calculate API costs for recipe articles"
    )
    parser.add_argument(
        "--articles",
        type=int,
        default=1,
        help="Number of articles to calculate costs for"
    )
    parser.add_argument(
        "--scenario",
        choices=["best", "typical", "worst"],
        default="typical",
        help="Cost scenario to use"
    )
    parser.add_argument(
        "--image-quality",
        choices=["standard", "high"],
        default="high",
        help="Image quality setting"
    )
    parser.add_argument(
        "--num-images",
        type=int,
        default=3,
        help="Number of images per article"
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip GPT extraction (assumes good JSON-LD)"
    )
    parser.add_argument(
        "--skip-enrichment",
        action="store_true",
        help="Skip metadata enrichment"
    )
    parser.add_argument(
        "--skip-vision",
        action="store_true",
        help="Skip vision-based prompt generation"
    )
    parser.add_argument(
        "--use-gpt-faqs",
        action="store_true",
        help="Use GPT for FAQ generation (instead of search APIs)"
    )
    
    args = parser.parse_args()
    
    # Determine scenario settings
    if args.scenario == "best":
        use_extraction = False
        use_enrichment = False
        use_vision = True
        use_gpt_faqs = False
        use_serper = True
    elif args.scenario == "worst":
        use_extraction = True
        use_enrichment = True
        use_vision = True
        use_gpt_faqs = True
        use_serper = True
    else:  # typical
        use_extraction = False
        use_enrichment = True
        use_vision = True
        use_gpt_faqs = True
        use_serper = True
    
    # Override with command-line arguments
    if args.skip_extraction:
        use_extraction = False
    if args.skip_enrichment:
        use_enrichment = False
    if args.skip_vision:
        use_vision = False
    if args.use_gpt_faqs:
        use_gpt_faqs = True
        use_serper = False
    
    # Calculate costs
    costs = calculate_article_cost(
        use_gpt_extraction=use_extraction,
        use_metadata_enrichment=use_enrichment,
        use_vision_prompts=use_vision,
        use_gpt_faqs=use_gpt_faqs,
        use_serper=use_serper,
        num_images=args.num_images,
        image_quality=args.image_quality
    )
    
    # Print results
    print("\n" + "=" * 60)
    print("RECIPE PIPELINE - API COST CALCULATOR")
    print("=" * 60)
    
    print_cost_breakdown(costs, f"Cost per Article ({args.scenario} case)")
    
    if args.articles > 1:
        total_cost = costs["total"] * args.articles
        print(f"\nTotal Cost for {args.articles} Articles:")
        print("-" * 60)
        print(f"  Per Article:  ${costs['total']:.4f}")
        print(f"  Total:        ${total_cost:.4f}")
        print(f"  Total (rounded): ${total_cost:.2f}")
        print()
    
    # Show optimization tips
    if costs["total"] > 0.30:
        print("\n💡 Cost Optimization Tips:")
        print("-" * 60)
        if costs["images"] > 0.25:
            print("  • Use 'standard' image quality to save ~20% on images")
        if costs["extraction"] > 0:
            print("  • Ensure recipes have good JSON-LD to skip GPT extraction")
        if costs["enrichment"] > 0:
            print("  • Ensure complete recipe metadata to skip enrichment")
        if costs["faqs_gpt"] > 0 and not use_serper:
            print("  • Use Serper API for FAQs (cheaper than GPT)")
        print()


if __name__ == "__main__":
    main()

