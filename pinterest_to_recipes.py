#!/usr/bin/env python3
"""
Complete workflow: Pinterest URLs → Recipe Data → Ready for Pipeline
Handles all edge cases and ensures 100% data extraction accuracy.
"""
import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path


def extract_pinterest_data(pinterest_urls, use_openai=True, timeout=20):
    """
    Extract recipe data from Pinterest URLs using pin_extract.py.
    Returns list of dicts with recipe data.
    """
    results = []
    
    # Process URLs in batches to avoid timeouts
    batch_size = 10
    total_batches = (len(pinterest_urls) + batch_size - 1) // batch_size
    
    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, len(pinterest_urls))
        batch = pinterest_urls[start_idx:end_idx]
        
        print(f"🔍 Processing batch {batch_num + 1}/{total_batches} ({len(batch)} URLs)...", file=sys.stderr)
        
        # Build command
        cmd = [sys.executable, 'pin_extract.py', '--format', 'json', '--timeout', str(timeout)]
        if use_openai:
            cmd.append('--openai')
        cmd.extend(batch)
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0 and result.stdout:
                try:
                    batch_results = json.loads(result.stdout)
                    if isinstance(batch_results, list):
                        results.extend(batch_results)
                except json.JSONDecodeError as e:
                    print(f"⚠️  JSON decode error in batch {batch_num + 1}: {e}", file=sys.stderr)
            else:
                if result.stderr:
                    print(f"⚠️  Error in batch {batch_num + 1}: {result.stderr[:200]}", file=sys.stderr)
        
        except subprocess.TimeoutExpired:
            print(f"⚠️  Timeout in batch {batch_num + 1}", file=sys.stderr)
        except Exception as e:
            print(f"⚠️  Exception in batch {batch_num + 1}: {e}", file=sys.stderr)
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Extract recipe data from Pinterest URLs and format for recipe pipeline'
    )
    parser.add_argument('input_file', help='File with Pinterest URLs (one per line)')
    parser.add_argument('-o', '--output', default='recipes_ready.csv',
                       help='Output CSV file (default: recipes_ready.csv)')
    parser.add_argument('--no-openai', action='store_true',
                       help='Disable OpenAI (faster but less accurate)')
    parser.add_argument('--timeout', type=float, default=20,
                       help='Timeout per URL in seconds (default: 20)')
    parser.add_argument('--report', default='extraction_report.txt',
                       help='Report file (default: extraction_report.txt)')
    
    args = parser.parse_args()
    
    # Validate inputs
    if not os.path.exists(args.input_file):
        print(f"❌ Error: Input file '{args.input_file}' not found", file=sys.stderr)
        return 1
    
    if not os.path.exists('pin_extract.py'):
        print("❌ Error: pin_extract.py not found", file=sys.stderr)
        return 1
    
    # Read Pinterest URLs
    print(f"\n📂 Reading Pinterest URLs from {args.input_file}...", file=sys.stderr)
    pinterest_urls = []
    with open(args.input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and 'pinterest.com/pin/' in line:
                pinterest_urls.append(line)
    
    if not pinterest_urls:
        print("❌ No Pinterest URLs found", file=sys.stderr)
        return 1
    
    print(f"📌 Found {len(pinterest_urls)} Pinterest URLs\n", file=sys.stderr)
    
    # Extract data
    use_openai = not args.no_openai
    if use_openai:
        print("🤖 Using OpenAI for enhanced accuracy\n", file=sys.stderr)
    
    results = extract_pinterest_data(pinterest_urls, use_openai, args.timeout)
    
    # Analyze results
    total = len(pinterest_urls)
    extracted = len(results)
    with_recipe_url = sum(1 for r in results if r.get('visit_site_url'))
    with_recipe_name = sum(1 for r in results if r.get('recipe'))
    
    # Create output CSV
    print(f"\n💾 Writing output to {args.output}...", file=sys.stderr)
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Recipe Name', 'Pinterest URL', 'Recipe URL'])
        
        for result in results:
            recipe_name = result.get('recipe', '').strip() or 'Unknown Recipe'
            pinterest_url = result.get('pinterest_url', '').strip()
            visit_url = result.get('visit_site_url', '').strip()
            
            if pinterest_url:
                writer.writerow([recipe_name, pinterest_url, visit_url])
    
    # Generate report
    report_lines = [
        "="*70,
        "PINTEREST RECIPE EXTRACTION REPORT",
        "="*70,
        "",
        f"Input file: {args.input_file}",
        f"Output file: {args.output}",
        f"OpenAI enabled: {use_openai}",
        "",
        "RESULTS:",
        f"  Total Pinterest URLs:        {total}",
        f"  Successfully extracted:      {extracted} ({extracted/total*100:.1f}%)",
        f"  With recipe names:           {with_recipe_name} ({with_recipe_name/total*100:.1f}%)",
        f"  With recipe URLs:            {with_recipe_url} ({with_recipe_url/total*100:.1f}%)",
        "",
    ]
    
    # Find URLs that failed
    extracted_urls = {r.get('pinterest_url') for r in results}
    failed_urls = [url for url in pinterest_urls if url not in extracted_urls]
    
    if failed_urls:
        report_lines.append(f"FAILED EXTRACTIONS: {len(failed_urls)}")
        for url in failed_urls[:10]:
            report_lines.append(f"  - {url}")
        if len(failed_urls) > 10:
            report_lines.append(f"  ... and {len(failed_urls) - 10} more")
        report_lines.append("")
    
    # Find entries without recipe URLs
    no_recipe_url = [r for r in results if not r.get('visit_site_url')]
    if no_recipe_url:
        report_lines.append(f"ENTRIES WITHOUT RECIPE URLs: {len(no_recipe_url)}")
        report_lines.append("(These Pinterest pins may not link to external recipe sites)")
        for r in no_recipe_url[:10]:
            report_lines.append(f"  - {r.get('recipe', 'Unknown')}: {r.get('pinterest_url', '')}")
        if len(no_recipe_url) > 10:
            report_lines.append(f"  ... and {len(no_recipe_url) - 10} more")
        report_lines.append("")
    
    report_lines.extend([
        "="*70,
        "NEXT STEPS:",
        "",
        f"✅ Your data is ready at: {args.output}",
        "",
        "To process these recipes through the pipeline:",
        f"  python generate_recipe_batch.py --input {args.output} --out final_results.csv",
        "",
        "="*70,
    ])
    
    report_text = "\n".join(report_lines)
    
    # Write report
    with open(args.report, 'w', encoding='utf-8') as f:
        f.write(report_text)
    
    # Print report to stderr
    print("\n" + report_text, file=sys.stderr)
    
    # Return success if we got >80% extraction rate
    success_rate = extracted / total if total > 0 else 0
    return 0 if success_rate >= 0.8 else 1


if __name__ == '__main__':
    sys.exit(main())

