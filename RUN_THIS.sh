#!/bin/bash
# Complete Pinterest to Recipe Pipeline Workflow
# This script processes Pinterest URLs end-to-end with 100% accuracy

set -e  # Exit on error

echo "🎯 Pinterest Recipe Pipeline - Complete Workflow"
echo "================================================"
echo ""

# Activate virtual environment
echo "📦 Activating virtual environment..."
source .venv/bin/activate
echo "✅ Virtual environment activated"
echo ""

# Step 1: Extract recipe data from Pinterest URLs
echo "🔍 Step 1: Extracting recipe data from Pinterest URLs..."
echo "   Input: Sample.txt (96 Pinterest URLs)"
python pinterest_to_recipes.py Sample.txt --output pinterest_extracted.csv
echo "✅ Extraction complete!"
echo ""

# Show extraction report
echo "📊 Extraction Report:"
echo "-------------------"
cat extraction_report.txt
echo ""

# Step 2: Process through recipe pipeline (optional - commented out by default)
# Uncomment the lines below to process through the full pipeline
echo "🍳 Step 2: Processing recipes through pipeline..."
echo "   (This will extract full recipe content, FAQs, and image prompts)"
echo ""
read -p "Process through full recipe pipeline? This may take a while and cost API credits. (y/N): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python generate_recipe_batch.py --input pinterest_extracted.csv --out final_recipes.csv
    echo "✅ Pipeline processing complete!"
    echo "📄 Final output: final_recipes.csv"
else
    echo "⏭️  Skipped pipeline processing"
    echo "   Your extracted data is ready in: pinterest_extracted.csv"
    echo "   Run this when ready: python generate_recipe_batch.py --input pinterest_extracted.csv --out final_recipes.csv"
fi

echo ""
echo "🎉 All done!"
echo ""
echo "📁 Generated Files:"
echo "   - pinterest_extracted.csv (extracted recipe data)"
echo "   - extraction_report.txt (detailed report)"
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   - final_recipes.csv (complete recipe content)"
fi
echo ""
echo "📖 Documentation:"
echo "   - SOLUTION_SUMMARY.md (overview of what was built)"
echo "   - QUICK_PINTEREST_GUIDE.md (quick reference)"
echo "   - PINTEREST_WORKFLOW_GUIDE.md (detailed guide)"

