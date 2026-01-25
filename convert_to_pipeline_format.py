#!/usr/bin/env python3
"""
Convert pin_extract.py output to generate_recipe_batch.py input format.
"""
import csv
import sys


def convert_format(input_csv, output_csv):
    """
    Convert from pin_extract format to pipeline format.
    
    Input: recipe, keywords, pinterest_url, visit_site_url
    Output: Recipe Name, Pinterest URL, Recipe URL
    """
    with_urls = 0
    without_urls = 0
    
    with open(input_csv, 'r', encoding='utf-8') as fin, \
         open(output_csv, 'w', newline='', encoding='utf-8') as fout:
        
        reader = csv.DictReader(fin)
        writer = csv.writer(fout)
        
        # Write header
        writer.writerow(['Recipe Name', 'Pinterest URL', 'Recipe URL'])
        
        for row in reader:
            recipe_name = row.get('recipe', '').strip()
            pinterest_url = row.get('pinterest_url', '').strip()
            visit_url = row.get('visit_site_url', '').strip()
            
            # Only include rows with Pinterest URLs
            if pinterest_url:
                # Use recipe name if available, otherwise use "Unknown Recipe"
                if not recipe_name:
                    recipe_name = 'Unknown Recipe'
                
                writer.writerow([recipe_name, pinterest_url, visit_url])
                
                if visit_url:
                    with_urls += 1
                else:
                    without_urls += 1
    
    return with_urls, without_urls


def main():
    if len(sys.argv) < 2:
        print("Usage: python convert_to_pipeline_format.py <input.csv> [output.csv]")
        print("\nConverts pin_extract.py output to generate_recipe_batch.py input format")
        return 1
    
    input_csv = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else 'pipeline_ready.csv'
    
    print(f"📂 Converting {input_csv} to pipeline format...")
    
    try:
        with_urls, without_urls = convert_format(input_csv, output_csv)
        total = with_urls + without_urls
        
        print(f"\n✅ Conversion complete!")
        print(f"📊 Total recipes: {total}")
        print(f"   ✓ With recipe URLs: {with_urls} ({with_urls/total*100:.1f}%)")
        print(f"   ⚠  Without recipe URLs: {without_urls} ({without_urls/total*100:.1f}%)")
        print(f"\n💾 Output saved to: {output_csv}")
        print(f"\n🚀 Ready to process with:")
        print(f"   python generate_recipe_batch.py --input {output_csv} --out results.csv")
        
        return 0
        
    except FileNotFoundError:
        print(f"❌ Error: File '{input_csv}' not found")
        return 1
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())

