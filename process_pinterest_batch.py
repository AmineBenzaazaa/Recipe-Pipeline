#!/usr/bin/env python3
"""
Enhanced Pinterest batch processor with validation and retry logic.
Ensures no recipes are missed and provides detailed reporting.
"""
import argparse
import csv
import os
import subprocess
import sys
import time
from pathlib import Path


def extract_pinterest_urls(input_file):
    """Extract all Pinterest URLs from input file."""
    urls = []
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and 'pinterest.com/pin/' in line:
                urls.append(line)
    return urls


def run_pin_extract(urls, use_openai=True, retries=2):
    """
    Run pin_extract.py and return results with retry logic.
    """
    results = {}
    failed_urls = list(urls)
    
    for attempt in range(retries):
        if not failed_urls:
            break
            
        print(f"\n🔍 Extraction attempt {attempt + 1}/{retries} for {len(failed_urls)} URLs...", file=sys.stderr)
        
        # Create temp file with URLs to process
        temp_input = f"temp_pinterest_urls_{attempt}.txt"
        with open(temp_input, 'w') as f:
            for url in failed_urls:
                f.write(f"{url}\n")
        
        # Run pin_extract.py
        cmd = [
            sys.executable,
            "pin_extract.py",
            "--file", temp_input,
            "--format", "csv"
        ]
        
        if use_openai:
            cmd.append("--openai")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            # Parse CSV output
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:  # Has header + data
                reader = csv.DictReader(lines)
                for row in reader:
                    pinterest_url = row.get('pinterest_url', '').strip()
                    recipe_name = row.get('recipe', '').strip()
                    visit_url = row.get('visit_site_url', '').strip()
                    keywords = row.get('keywords', '').strip()
                    
                    if pinterest_url:
                        results[pinterest_url] = {
                            'recipe': recipe_name,
                            'visit_url': visit_url,
                            'keywords': keywords,
                            'status': 'success' if (recipe_name or visit_url) else 'empty'
                        }
                        # Remove from failed list if we got something
                        if pinterest_url in failed_urls and (recipe_name or visit_url):
                            failed_urls.remove(pinterest_url)
        
        except subprocess.TimeoutExpired:
            print(f"⚠️  Timeout on attempt {attempt + 1}", file=sys.stderr)
        except Exception as e:
            print(f"⚠️  Error on attempt {attempt + 1}: {e}", file=sys.stderr)
        
        finally:
            # Cleanup temp file
            if os.path.exists(temp_input):
                os.remove(temp_input)
        
        # Wait before retry
        if failed_urls and attempt < retries - 1:
            print(f"⏳ Waiting 2 seconds before retry...", file=sys.stderr)
            time.sleep(2)
    
    return results, failed_urls


def validate_results(all_urls, results, failed_urls):
    """Validate extraction results and provide detailed report."""
    total = len(all_urls)
    successful = len([r for r in results.values() if r['status'] == 'success'])
    empty = len([r for r in results.values() if r['status'] == 'empty'])
    failed = len(failed_urls)
    
    print("\n" + "="*60, file=sys.stderr)
    print("📊 EXTRACTION REPORT", file=sys.stderr)
    print("="*60, file=sys.stderr)
    print(f"Total Pinterest URLs:     {total}", file=sys.stderr)
    print(f"✅ Successfully extracted: {successful} ({successful/total*100:.1f}%)", file=sys.stderr)
    print(f"⚠️  Empty data:            {empty} ({empty/total*100:.1f}%)", file=sys.stderr)
    print(f"❌ Failed to extract:      {failed} ({failed/total*100:.1f}%)", file=sys.stderr)
    print("="*60, file=sys.stderr)
    
    # Report URLs with recipe names but no visit URLs
    no_visit_url = [url for url, data in results.items() 
                    if data['recipe'] and not data['visit_url']]
    if no_visit_url:
        print(f"\n⚠️  {len(no_visit_url)} pins have recipe names but NO external recipe URLs:", file=sys.stderr)
        print("   (These pins may just be images without linked recipes)", file=sys.stderr)
    
    # Report completely failed URLs
    if failed_urls:
        print(f"\n❌ {len(failed_urls)} URLs failed completely:", file=sys.stderr)
        for url in failed_urls[:5]:  # Show first 5
            print(f"   - {url}", file=sys.stderr)
        if len(failed_urls) > 5:
            print(f"   ... and {len(failed_urls) - 5} more", file=sys.stderr)
    
    return successful, total


def write_output_csv(results, output_file, format_type='pipeline'):
    """
    Write results to CSV in the specified format.
    
    format_type:
        'pipeline' - Format for generate_recipe_batch.py (Recipe Name, Pinterest URL, Recipe URL)
        'full' - Full format with all fields including keywords
    """
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        if format_type == 'pipeline':
            writer = csv.writer(f)
            writer.writerow(['Recipe Name', 'Pinterest URL', 'Recipe URL'])
            
            for pinterest_url, data in results.items():
                recipe_name = data['recipe'] or 'Unknown Recipe'
                visit_url = data['visit_url'] or ''
                writer.writerow([recipe_name, pinterest_url, visit_url])
        
        else:  # full format
            writer = csv.writer(f)
            writer.writerow(['Recipe Name', 'Keywords', 'Pinterest URL', 'Recipe URL', 'Status'])
            
            for pinterest_url, data in results.items():
                writer.writerow([
                    data['recipe'],
                    data['keywords'],
                    pinterest_url,
                    data['visit_url'],
                    data['status']
                ])


def main():
    parser = argparse.ArgumentParser(
        description='Enhanced Pinterest batch processor with validation and retry'
    )
    parser.add_argument('input_file', help='File with Pinterest URLs (one per line)')
    parser.add_argument('-o', '--output', default='pinterest_extracted.csv',
                       help='Output CSV file (default: pinterest_extracted.csv)')
    parser.add_argument('--format', choices=['pipeline', 'full'], default='pipeline',
                       help='Output format: pipeline (for generate_recipe_batch.py) or full (all fields)')
    parser.add_argument('--no-openai', action='store_true',
                       help='Disable OpenAI extraction (faster but less accurate)')
    parser.add_argument('--retries', type=int, default=2,
                       help='Number of retry attempts (default: 2)')
    
    args = parser.parse_args()
    
    # Check if input file exists
    if not os.path.exists(args.input_file):
        print(f"❌ Error: Input file '{args.input_file}' not found", file=sys.stderr)
        return 1
    
    # Check if pin_extract.py exists
    if not os.path.exists('pin_extract.py'):
        print("❌ Error: pin_extract.py not found in current directory", file=sys.stderr)
        return 1
    
    # Extract Pinterest URLs from input
    print(f"📂 Reading Pinterest URLs from {args.input_file}...", file=sys.stderr)
    urls = extract_pinterest_urls(args.input_file)
    
    if not urls:
        print("❌ No Pinterest URLs found in input file", file=sys.stderr)
        return 1
    
    print(f"📌 Found {len(urls)} Pinterest URLs", file=sys.stderr)
    
    # Extract recipe data with retry logic
    use_openai = not args.no_openai
    if use_openai:
        print("🤖 Using OpenAI for enhanced accuracy", file=sys.stderr)
    else:
        print("⚡ Using fast extraction (no OpenAI)", file=sys.stderr)
    
    results, failed_urls = run_pin_extract(urls, use_openai, args.retries)
    
    # Validate and report results
    successful, total = validate_results(urls, results, failed_urls)
    
    # Write output CSV
    write_output_csv(results, args.output, args.format)
    print(f"\n✅ Output written to: {args.output}", file=sys.stderr)
    
    # Return success if we got at least 80% success rate
    success_rate = successful / total if total > 0 else 0
    if success_rate >= 0.8:
        print(f"\n🎉 Extraction completed successfully ({success_rate*100:.1f}% success rate)", file=sys.stderr)
        return 0
    else:
        print(f"\n⚠️  Extraction completed with low success rate ({success_rate*100:.1f}%)", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

